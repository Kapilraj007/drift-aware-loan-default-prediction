"""Re-evaluate the locked Sprint 2 primary model by temporal split and quarter."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from drift_loan.data import ISSUE_QUARTER_COLUMN, TARGET_COLUMN
from drift_loan.modeling import (
    evaluate_binary_predictions,
    load_model_bundle,
    load_modeling_dataset,
)


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _split_report(
    frame: Any,
    *,
    feature_names: tuple[str, ...],
    predictor: Any,
    threshold: float,
    split_name: str,
) -> dict[str, Any]:
    scores = predictor.predict_proba_features(frame.loc[:, list(feature_names)])
    overall = evaluate_binary_predictions(
        frame[TARGET_COLUMN],
        scores,
        threshold=threshold,
        split_name=split_name,
    ).to_dict()
    per_quarter: dict[str, dict[str, Any]] = {}
    for quarter, subset in frame.groupby(ISSUE_QUARTER_COLUMN, sort=True, observed=True):
        quarter_scores = predictor.predict_proba_features(subset.loc[:, list(feature_names)])
        per_quarter[str(quarter)] = evaluate_binary_predictions(
            subset[TARGET_COLUMN],
            quarter_scores,
            threshold=threshold,
            split_name=f"{split_name} {quarter}",
        ).to_dict()
    return {"overall": overall, "per_quarter": per_quarter}


def evaluate(
    feature_store: Path,
    model_directory: Path,
) -> dict[str, Any]:
    """Score validation and locked shift data using the persisted primary model."""

    bundle = load_model_bundle(model_directory)
    dataset = load_modeling_dataset(feature_store)
    feature_view = str(bundle.metadata.get("feature_view", "unscaled"))
    reports = {
        split: _split_report(
            dataset.split_frame(split, feature_view=feature_view),
            feature_names=bundle.feature_names,
            predictor=bundle,
            threshold=bundle.threshold,
            split_name=split,
        )
        for split in ("validation", "shift")
    }
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "model_version": bundle.model_version,
        "model_directory": str(model_directory.resolve()),
        "feature_store": str(feature_store.resolve()),
        "feature_view": feature_view,
        "prediction_threshold": bundle.threshold,
        "feature_count": len(bundle.feature_names),
        "reports": reports,
        "interpretation_note": (
            "The shift split is held out from model and threshold selection. Late 2018 labels "
            "have documented maturity/censoring limitations; use the per-quarter results rather "
            "than treating the aggregate as a current-deployment claim."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the persisted Sprint 2 primary model by temporal split and quarter."
    )
    parser.add_argument("--feature-store", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = evaluate(args.feature_store, args.model_directory)
    _write_json_atomically(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
