"""Validate the persisted Sprint 1 feature store without loading it all into RAM."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from drift_loan.data.data_dictionary import DATA_DICTIONARY_COLUMNS
from drift_loan.data.schema import (
    ISSUE_DATE_COLUMN,
    ISSUE_QUARTER_COLUMN,
    LEAKAGE_COLUMNS,
    SPLIT_COLUMN,
    TARGET_COLUMN,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _partition_files(root: Path, variant: str) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted((root / variant).glob(f"{ISSUE_QUARTER_COLUMN}=*/part-*.parquet")):
        quarter = path.parent.name.split("=", maxsplit=1)[1]
        if quarter in files:
            raise ValueError(f"Duplicate {variant} partition for {quarter}")
        files[quarter] = path
    return files


def _load_acquisition_row(path: Path, source_id: str) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as stream:
        matches = [row for row in csv.DictReader(stream) if row["source_id"] == source_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one acquisition row for {source_id!r}; found {len(matches)}")
    return matches[0]


def validate_feature_store(
    root: Path,
    *,
    acquisition_manifest: Path | None = None,
    source_id: str = "lendingclub_kaggle_v3",
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    features = list(manifest["feature_names"])
    forbidden = sorted(set(features) & set(LEAKAGE_COLUMNS))
    if forbidden:
        raise ValueError(f"Leakage columns reached the feature matrix: {forbidden}")

    expected_quarters = list(manifest["partitions"])
    if expected_quarters != sorted(expected_quarters):
        raise ValueError("Manifest partitions are not chronological")
    unscaled_files = _partition_files(root, "unscaled")
    scaled_files = _partition_files(root, "scaled")
    if list(unscaled_files) != expected_quarters or list(scaled_files) != expected_quarters:
        raise ValueError("Scaled/unscaled partition inventory differs from the manifest")

    split_counts: Counter[str] = Counter()
    target_counts: Counter[int] = Counter()
    scaled_train_sum = np.zeros(len(features), dtype=np.float64)
    scaled_train_rows = 0

    expected_physical = [ISSUE_DATE_COLUMN, SPLIT_COLUMN, TARGET_COLUMN, *features]
    for quarter in expected_quarters:
        unscaled = pd.read_parquet(unscaled_files[quarter])
        if list(unscaled.columns) != expected_physical:
            raise ValueError(f"Unexpected unscaled schema in {quarter}")
        if unscaled[features].isna().any().any():
            raise ValueError(f"Missing model values in unscaled {quarter}")
        if not np.isfinite(unscaled[features].to_numpy(dtype=np.float64)).all():
            raise ValueError(f"Non-finite model values in unscaled {quarter}")
        issue_dates = pd.to_datetime(unscaled[ISSUE_DATE_COLUMN], errors="raise")
        if not (issue_dates.dt.to_period("Q").astype(str) == quarter).all():
            raise ValueError(f"Issue dates do not match partition {quarter}")
        split_values = unscaled[SPLIT_COLUMN].unique().tolist()
        expected_split = manifest["quarter_to_split"][quarter]
        if split_values != [expected_split]:
            raise ValueError(f"Partition {quarter} has split values {split_values}")
        targets = pd.to_numeric(unscaled[TARGET_COLUMN], errors="raise").astype("int8")
        if not set(targets.unique()).issubset({0, 1}):
            raise ValueError(f"Non-binary target in {quarter}")
        split_counts[expected_split] += len(unscaled)
        target_counts.update(int(value) for value in targets)
        metadata = unscaled[[ISSUE_DATE_COLUMN, SPLIT_COLUMN, TARGET_COLUMN]].reset_index(
            drop=True
        )
        del unscaled

        scaled = pd.read_parquet(scaled_files[quarter])
        if list(scaled.columns) != expected_physical:
            raise ValueError(f"Unexpected scaled schema in {quarter}")
        pd.testing.assert_frame_equal(
            metadata,
            scaled[[ISSUE_DATE_COLUMN, SPLIT_COLUMN, TARGET_COLUMN]].reset_index(drop=True),
            check_dtype=True,
        )
        scaled_values = scaled[features].to_numpy(dtype=np.float64)
        if not np.isfinite(scaled_values).all():
            raise ValueError(f"Non-finite model values in scaled {quarter}")
        if expected_split == "train":
            scaled_train_sum += scaled_values.sum(axis=0)
            scaled_train_rows += len(scaled)
        del metadata, scaled, scaled_values

    observed_counts = {name: split_counts[name] for name in sorted(split_counts)}
    expected_counts = {name: int(value) for name, value in manifest["row_counts"].items()}
    if observed_counts != expected_counts:
        raise ValueError(
            f"Observed split counts {observed_counts} differ from manifest {expected_counts}"
        )
    if sum(observed_counts.values()) != int(manifest["total_rows"]):
        raise ValueError("Manifest total_rows does not equal partition row counts")

    artifacts = root / manifest["artifact_directory"]
    for filename, expected_hash in manifest["artifact_sha256"].items():
        if _sha256(artifacts / filename) != expected_hash:
            raise ValueError(f"Artifact hash mismatch: {filename}")
    dictionary_path = root / manifest["data_dictionary"]
    if _sha256(dictionary_path) != manifest["data_dictionary_sha256"]:
        raise ValueError("Data dictionary hash mismatch")
    dictionary = pd.read_csv(dictionary_path)
    if tuple(dictionary.columns) != DATA_DICTIONARY_COLUMNS:
        raise ValueError("Data dictionary columns do not match the required contract")
    dictionary_features = set(dictionary.loc[~dictionary["leakage_risk_flag"], "feature_name"])
    if dictionary_features != set(features):
        raise ValueError("Data dictionary model features differ from the manifest schema")

    source_path, source_size = manifest["pipeline_metadata"]["ingestion"]["source_bytes"][0]
    _, source_hash = manifest["pipeline_metadata"]["ingestion"]["source_sha256"][0]
    if acquisition_manifest is not None:
        acquisition = _load_acquisition_row(acquisition_manifest.resolve(), source_id)
        if int(acquisition["pipeline_input_size_bytes"]) != int(source_size):
            raise ValueError("Acquisition and build input sizes differ")
        if acquisition["pipeline_input_sha256"] != source_hash:
            raise ValueError("Acquisition and build input hashes differ")

    train_means = scaled_train_sum / scaled_train_rows
    return {
        "status": "passed",
        "feature_store": str(root),
        "source_path": source_path,
        "source_size_bytes": int(source_size),
        "source_sha256": source_hash,
        "partition_count": len(expected_quarters),
        "minimum_issue_quarter": expected_quarters[0],
        "maximum_issue_quarter": expected_quarters[-1],
        "feature_count": len(features),
        "row_counts": observed_counts,
        "total_rows": int(manifest["total_rows"]),
        "target_counts": {str(key): target_counts[key] for key in sorted(target_counts)},
        "leakage_feature_intersection": forbidden,
        "non_finite_model_values": 0,
        "max_abs_scaled_train_mean": float(np.abs(train_means).max()),
        "artifact_hashes_verified": len(manifest["artifact_sha256"]),
        "data_dictionary_hash_verified": True,
        "acquisition_link_verified": acquisition_manifest is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_store", type=Path)
    parser.add_argument("--acquisition-manifest", type=Path)
    parser.add_argument("--source-id", default="lendingclub_kaggle_v3")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_feature_store(
        args.feature_store,
        acquisition_manifest=args.acquisition_manifest,
        source_id=args.source_id,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
