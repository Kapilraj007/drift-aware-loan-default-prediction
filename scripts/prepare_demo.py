"""Prepare the complete synthetic showcase without changing model science.

The command generates deterministic LendingClub-shaped data, builds the
existing leakage-safe feature store, trains all three existing model families,
marks the resulting bundle as synthetic, writes drift cohorts, validates a
real score, migrates Neon, and seeds the small application demo dataset.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from generate_demo_data import write_demo_csv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.services.inference_service import InferenceService  # noqa: E402
from drift_loan.data import build_feature_store_from_csv  # noqa: E402
from drift_loan.drift import (  # noqa: E402
    PerturbationSpec,
    TimeWindow,
    load_feature_window,
    run_drift_simulation,
)
from drift_loan.modeling import TrainingConfig, train_sprint2_models  # noqa: E402

DEFAULT_ROWS = 20_000
SAMPLE_LIMIT = 500

SAMPLE_APPLICATION: dict[str, object] = {
    "annual_inc": 75_000,
    "dti": 16.5,
    "revol_util": "38%",
    "revol_bal": 28_000,
    "open_acc": 10,
    "total_acc": 22,
    "delinq_2yrs": 0,
    "inq_last_6mths": 1,
    "loan_amnt": 12_000,
    "term": "36 months",
    "int_rate": "11.2%",
    "installment": 395,
    "grade": "B",
    "sub_grade": "B3",
    "purpose": "debt_consolidation",
    "emp_length": "5 years",
    "home_ownership": "MORTGAGE",
    "earliest_cr_line": "Jan-2004",
    "issue_d": "Jan-2018",
}


def _step(message: str) -> float:
    print(f"\n==> {message}", flush=True)
    return time.perf_counter()


def _finished(started: float) -> None:
    print(f"    completed in {time.perf_counter() - started:.1f}s", flush=True)


def _write_sample_application(samples: Path) -> None:
    samples.mkdir(parents=True, exist_ok=True)
    (samples / "sample-application.json").write_text(
        json.dumps(SAMPLE_APPLICATION, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    header = ",".join(SAMPLE_APPLICATION)
    values = ",".join(str(value) for value in SAMPLE_APPLICATION.values())
    (samples / "sample-application.csv").write_text(
        f"{header}\n{values}\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_drift_samples(feature_store: Path, samples: Path, seed: int) -> None:
    window = TimeWindow(
        start="2018-01-01",
        end="2018-12-31T23:59:59Z",
        include_end=True,
    )
    reference = load_feature_window(
        feature_store,
        window=window,
        feature_view="unscaled",
    ).frame.head(SAMPLE_LIMIT)
    drifted = run_drift_simulation(
        feature_store,
        window=window,
        perturbations=(
            PerturbationSpec(feature="int_rate", shift=4.0, clip=(0.0, 40.0)),
            PerturbationSpec(feature="dti", shift=8.0, clip=(0.0, 100.0)),
        ),
        seed=seed,
        feature_view="unscaled",
    )
    samples.mkdir(parents=True, exist_ok=True)
    reference.to_csv(samples / "reference_cohort.csv", index=False, encoding="utf-8")
    drifted.frame.head(SAMPLE_LIMIT).to_csv(
        samples / "current_cohort_drifted.csv",
        index=False,
        encoding="utf-8",
    )
    drifted.manifest.write_json(samples / "current_cohort_drifted.manifest.json")


def _verify_model(model_directory: Path, preprocessor_directory: Path) -> dict[str, object]:
    settings = Settings(
        database_url="postgresql+psycopg://demo:demo@example.invalid/demo?sslmode=require",
        direct_database_url=(
            "postgresql+psycopg://demo:demo@example.invalid/demo?sslmode=require"
        ),
        jwt_secret_key="demo-verification-secret-not-used-for-authentication",
        model_artifact_directory=model_directory,
        preprocessor_artifact_directory=preprocessor_directory,
    )
    service = InferenceService(settings)
    description = service.describe()
    result = service.predict(SAMPLE_APPLICATION)
    if not 0.0 <= result.score <= 1.0:
        raise RuntimeError("Real model verification returned an invalid probability")
    return {
        "model_version": description["model_version"],
        "synthetic_demo": bool(
            isinstance(description.get("metadata"), dict)
            and description["metadata"].get("synthetic_demo") is True
        ),
        "sample_score": round(result.score, 6),
        "risk_flag": result.risk_flag,
    }


def _migrate_and_seed() -> None:
    # Alembic's env.py intentionally reads DIRECT_DATABASE_URL.
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.db.seed",
            "--demo-users",
            "--demo-data",
            "--yes",
        ],
        cwd=ROOT,
        check=True,
    )


def prepare(args: argparse.Namespace) -> dict[str, object]:
    raw_csv = ROOT / args.raw_csv
    feature_store = ROOT / args.feature_store
    preprocessor = ROOT / args.preprocessor_directory
    model_directory = ROOT / args.model_directory
    samples = ROOT / args.samples_directory

    started = _step(f"Generating {args.rows:,} deterministic synthetic rows")
    write_demo_csv(raw_csv, args.rows, args.seed)
    _finished(started)

    started = _step("Building the leakage-safe feature store")
    pipeline = build_feature_store_from_csv(
        raw_csv,
        feature_store,
        artifact_directory=preprocessor,
        train_fraction=0.60,
        validation_fraction=0.20,
        shift_fraction=0.20,
        random_seed=args.seed,
        overwrite=True,
    )
    _finished(started)

    started = _step("Training LightGBM, XGBoost, and logistic regression")
    training = train_sprint2_models(
        feature_store,
        model_directory,
        config=TrainingConfig(
            random_seed=args.seed,
            cv_splits=args.cv_splits,
            synthetic_demo=True,
        ),
        overwrite=True,
    )
    _finished(started)

    started = _step("Writing application and drift-cohort samples")
    _write_sample_application(samples)
    _write_drift_samples(feature_store, samples, args.seed)
    _finished(started)

    started = _step("Loading the real bundle and scoring the sample application")
    verification = _verify_model(model_directory, preprocessor)
    if verification["synthetic_demo"] is not True:
        raise RuntimeError("Model metadata was not marked synthetic_demo=true")
    _finished(started)

    if not args.artifacts_only:
        # Fail before touching the database if the required settings are absent.
        Settings.from_environment()
        started = _step("Migrating and seeding the configured Neon showcase branch")
        _migrate_and_seed()
        _finished(started)

    summary = {
        "synthetic_rows": args.rows,
        "feature_store": str(pipeline.feature_store_root),
        "preprocessor": str(pipeline.artifact_directory),
        "model_directory": str(training.root),
        "samples_directory": str(samples),
        "database_prepared": not args.artifacts_only,
        "verification": verification,
    }
    print("\nDemo preparation complete:")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--cv-splits", type=int, default=3)
    parser.add_argument("--raw-csv", type=Path, default=Path("data/raw/demo_accepted_loans.csv"))
    parser.add_argument(
        "--feature-store", type=Path, default=Path("data/processed/feature_store")
    )
    parser.add_argument(
        "--preprocessor-directory",
        type=Path,
        default=Path("data/artifacts/preprocessor"),
    )
    parser.add_argument(
        "--model-directory", type=Path, default=Path("data/artifacts/model")
    )
    parser.add_argument("--samples-directory", type=Path, default=Path("samples"))
    parser.add_argument(
        "--artifacts-only",
        action="store_true",
        help="Prepare and verify local artifacts without migrating or seeding Neon.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.rows < DEFAULT_ROWS:
        raise SystemExit(f"--rows must be at least {DEFAULT_ROWS:,} for reliable temporal CV")
    prepare(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
