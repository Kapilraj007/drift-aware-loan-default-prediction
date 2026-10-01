"""Command-line entry points for the reproducible Sprint 1 workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from drift_loan import __version__
from drift_loan.data import DataPipelineError, build_feature_store_from_csv
from drift_loan.drift import PerturbationSpec, TimeWindow, run_drift_simulation
from drift_loan.modeling import ModelingError, TrainingConfig, train_sprint2_models


def _load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Pipeline configuration not found: {path}")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in pipeline configuration {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"Pipeline configuration {path} must contain a JSON object.")
    return loaded


def _coalesce(value: Any, fallback: Any) -> Any:
    return fallback if value is None else value


def _run_build(args: argparse.Namespace) -> int:
    config_path = args.config.expanduser().resolve()
    config = _load_config(config_path)
    split_config = config.get("time_split", {})
    if not isinstance(split_config, dict):
        raise ValueError("config.time_split must be a JSON object")

    configured_input = config.get("input_csv")
    inputs = args.input or ([configured_input] if configured_input else [])
    if not inputs:
        raise ValueError("At least one --input CSV or config.input_csv is required.")
    feature_store = _coalesce(args.feature_store, config.get("feature_store"))
    if feature_store is None:
        raise ValueError("--feature-store or config.feature_store is required.")
    artifact_directory = _coalesce(
        args.artifact_directory,
        config.get("artifact_directory"),
    )

    result = build_feature_store_from_csv(
        inputs,
        feature_store,
        artifact_directory=artifact_directory,
        train_fraction=float(
            _coalesce(args.train_fraction, split_config.get("train_fraction", 0.60))
        ),
        validation_fraction=float(
            _coalesce(args.validation_fraction, split_config.get("validation_fraction", 0.20))
        ),
        shift_fraction=float(
            _coalesce(args.shift_fraction, split_config.get("shift_fraction", 0.20))
        ),
        chunk_size=_coalesce(args.chunk_size, config.get("chunk_size")),
        random_seed=_coalesce(args.seed, config.get("random_seed")),
        overwrite=args.overwrite,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


def _clip(lower: float | None, upper: float | None) -> tuple[float | None, float | None] | None:
    return None if lower is None and upper is None else (lower, upper)


def _add_perturbation(
    specs: list[PerturbationSpec],
    *,
    feature: str,
    shift: float | None,
    mode: str,
    fraction: float,
    lower: float | None,
    upper: float | None,
) -> None:
    if shift is None:
        return
    specs.append(
        PerturbationSpec(
            feature=feature,
            shift=shift,
            mode=mode,
            fraction=fraction,
            clip=_clip(lower, upper),
        )
    )


def _run_simulation(args: argparse.Namespace) -> int:
    perturbations: list[PerturbationSpec] = []
    _add_perturbation(
        perturbations,
        feature="int_rate",
        shift=args.int_rate_shift,
        mode=args.int_rate_mode,
        fraction=args.int_rate_fraction,
        lower=args.int_rate_min,
        upper=args.int_rate_max,
    )
    _add_perturbation(
        perturbations,
        feature="dti",
        shift=args.dti_shift,
        mode=args.dti_mode,
        fraction=args.dti_fraction,
        lower=args.dti_min,
        upper=args.dti_max,
    )
    if not perturbations:
        raise ValueError(
            "Specify --int-rate-shift, --dti-shift, or both for a drift simulation."
        )

    result = run_drift_simulation(
        args.feature_store,
        window=TimeWindow(
            start=args.start,
            end=args.end,
            include_start=not args.exclude_start,
            include_end=args.include_end,
        ),
        perturbations=perturbations,
        seed=args.seed,
        feature_view=args.feature_view,
    )
    data_path, manifest_path = result.write(
        args.output,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {
                "data_path": str(data_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "rows_selected": len(result.frame),
                "seed": args.seed,
                "window": result.manifest.window.to_dict()
                if result.manifest.window is not None
                else None,
                "perturbations": [item.to_dict() for item in perturbations],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_train_model(args: argparse.Namespace) -> int:
    """Run the complete Sprint 2 temporal modeling workflow."""

    option_store = args.feature_store_option
    positional_store = args.feature_store
    if option_store is not None and positional_store is not None:
        if option_store.expanduser().resolve() != positional_store.expanduser().resolve():
            raise ValueError(
                "Positional feature_store and --feature-store must match when both are provided."
            )
    feature_store = option_store or positional_store
    if feature_store is None:
        raise ValueError("Provide a feature store positionally or with --feature-store.")
    result = train_sprint2_models(
        feature_store,
        args.output_dir,
        config=TrainingConfig(random_seed=args.seed, cv_splits=args.cv_splits),
        overwrite=args.overwrite,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drift-loan",
        description="Build and exercise the Sprint 1 drift-aware loan data foundation.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "build",
        help="Build a leakage-safe, time-partitioned Parquet feature store.",
    )
    build.add_argument("--config", type=Path, default=Path("config/pipeline.json"))
    build.add_argument("--input", action="append", help="Input CSV; repeat for multiple files.")
    build.add_argument("--feature-store", type=Path)
    build.add_argument("--artifact-directory", type=Path)
    build.add_argument("--train-fraction", type=float)
    build.add_argument("--validation-fraction", type=float)
    build.add_argument("--shift-fraction", type=float)
    build.add_argument("--chunk-size", type=int)
    build.add_argument("--seed", type=int)
    build.add_argument("--overwrite", action="store_true")
    build.set_defaults(handler=_run_build)

    simulate = commands.add_parser(
        "simulate-drift",
        help="Slice the store by time and apply reproducible interest-rate or DTI shifts.",
    )
    simulate.add_argument("feature_store", type=Path)
    simulate.add_argument("--output", type=Path, required=True)
    simulate.add_argument("--manifest", type=Path)
    simulate.add_argument("--start", help="UTC-compatible lower time bound.")
    simulate.add_argument("--end", help="UTC-compatible upper time bound.")
    simulate.add_argument("--exclude-start", action="store_true")
    simulate.add_argument("--include-end", action="store_true")
    simulate.add_argument("--seed", type=int, default=20260926)
    simulate.add_argument("--feature-view", choices=("unscaled", "scaled"), default="unscaled")

    for prefix, label in (("int-rate", "interest rate"), ("dti", "DTI")):
        destination = prefix.replace("-", "_")
        simulate.add_argument(
            f"--{prefix}-shift",
            dest=f"{destination}_shift",
            type=float,
            help=f"Synthetic {label} shift; relative mode uses a ratio such as 0.15.",
        )
        simulate.add_argument(
            f"--{prefix}-mode",
            dest=f"{destination}_mode",
            choices=("absolute", "relative"),
            default="absolute",
        )
        simulate.add_argument(
            f"--{prefix}-fraction",
            dest=f"{destination}_fraction",
            type=float,
            default=1.0,
        )
        simulate.add_argument(f"--{prefix}-min", dest=f"{destination}_min", type=float)
        simulate.add_argument(f"--{prefix}-max", dest=f"{destination}_max", type=float)
    simulate.set_defaults(handler=_run_simulation)

    train_model = commands.add_parser(
        "train-model",
        help=(
            "Train LightGBM, XGBoost, and logistic-regression models with "
            "expanding temporal validation."
        ),
    )
    train_model.add_argument("feature_store", type=Path, nargs="?")
    train_model.add_argument("--feature-store", dest="feature_store_option", type=Path)
    train_model.add_argument(
        "--output-dir",
        "--model-directory",
        dest="output_dir",
        type=Path,
        required=True,
    )
    train_model.add_argument("--seed", type=int, default=20260926)
    train_model.add_argument("--cv-splits", type=int, default=3)
    train_model.add_argument("--overwrite", action="store_true")
    train_model.set_defaults(handler=_run_train_model)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        DataPipelineError,
        ModelingError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
