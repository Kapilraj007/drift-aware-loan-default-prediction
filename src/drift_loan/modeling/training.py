"""Reproducible Sprint 2 temporal model training and artifact production."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Integral
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from drift_loan.data import ISSUE_DATE_COLUMN, ISSUE_QUARTER_COLUMN, TARGET_COLUMN

from .data import ModelingDataset, load_modeling_dataset
from .errors import ModelingDataError, ModelingError
from .estimators import (
    MODEL_NAMES,
    EstimatorFactory,
    create_estimator,
    positive_class_probabilities,
)
from .explanations import create_tree_explainer
from .metrics import (
    ClassificationMetrics,
    ThresholdSelection,
    evaluate_binary_predictions,
    select_validation_threshold,
)
from .monitoring import calibrate_adwin_detector

ARTIFACT_SCHEMA_VERSION = "1.0.0"
PRIMARY_MODEL_NAME = "lightgbm"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(
            _json_safe(payload),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ModelingDataError(f"Model parameters and metadata must be JSON-safe: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _feature_schema_sha256(feature_names: tuple[str, ...]) -> str:
    """Match the Sprint 1 train/serve feature-schema digest contract."""

    return hashlib.sha256("\n".join(feature_names).encode("utf-8")).hexdigest()


def _normalise_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    field_name: str,
) -> tuple[dict[str, Any], ...]:
    invalid_candidates = (
        isinstance(candidates, str | bytes)
        or not isinstance(candidates, Sequence)
        or not candidates
    )
    if invalid_candidates:
        raise ModelingDataError(
            f"{field_name} must be a non-empty sequence of parameter mappings."
        )
    normalised: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ModelingDataError(f"{field_name}[{index}] must be a parameter mapping.")
        prepared = {str(key): value for key, value in candidate.items()}
        # Validate now, before a long-running model fit begins.
        _canonical_json(prepared)
        normalised.append(dict(sorted(prepared.items())))
    return tuple(normalised)


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Deterministic parameters for all three Sprint 2 model families.

    The default candidate sets keep the full real-data run practical while the
    public candidate fields allow callers to provide a larger time-aware tuning
    grid without changing training logic.
    """

    random_seed: int = 20260926
    cv_splits: int = 3
    synthetic_demo: bool = False
    lightgbm_candidates: tuple[Mapping[str, Any], ...] = field(
        default_factory=lambda: (
            {
                "n_estimators": 200,
                "learning_rate": 0.05,
                "num_leaves": 31,
                "min_child_samples": 30,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_lambda": 1.0,
            },
        )
    )
    xgboost_candidates: tuple[Mapping[str, Any], ...] = field(
        default_factory=lambda: (
            {
                "n_estimators": 120,
                "learning_rate": 0.05,
                "max_depth": 5,
                "min_child_weight": 5,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_lambda": 1.0,
            },
        )
    )
    logistic_regression_candidates: tuple[Mapping[str, Any], ...] = field(
        default_factory=lambda: ({"C": 1.0, "max_iter": 1_000},)
    )

    def __post_init__(self) -> None:
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, Integral):
            raise ModelingDataError("random_seed must be a non-negative integer.")
        if self.random_seed < 0:
            raise ModelingDataError("random_seed must be a non-negative integer.")
        if isinstance(self.cv_splits, bool) or not isinstance(self.cv_splits, Integral):
            raise ModelingDataError("cv_splits must be a positive integer.")
        if self.cv_splits < 1:
            raise ModelingDataError("cv_splits must be a positive integer.")
        if not isinstance(self.synthetic_demo, bool):
            raise ModelingDataError("synthetic_demo must be a boolean.")
        object.__setattr__(self, "random_seed", int(self.random_seed))
        object.__setattr__(self, "cv_splits", int(self.cv_splits))
        object.__setattr__(
            self,
            "lightgbm_candidates",
            _normalise_candidates(self.lightgbm_candidates, field_name="lightgbm_candidates"),
        )
        object.__setattr__(
            self,
            "xgboost_candidates",
            _normalise_candidates(self.xgboost_candidates, field_name="xgboost_candidates"),
        )
        object.__setattr__(
            self,
            "logistic_regression_candidates",
            _normalise_candidates(
                self.logistic_regression_candidates,
                field_name="logistic_regression_candidates",
            ),
        )

    def candidates_for(self, model_name: str) -> tuple[dict[str, Any], ...]:
        if model_name == "lightgbm":
            return self.lightgbm_candidates
        if model_name == "xgboost":
            return self.xgboost_candidates
        if model_name == "logistic_regression":
            return self.logistic_regression_candidates
        raise ModelingDataError(f"model_name must be one of {MODEL_NAMES}; got {model_name!r}.")


@dataclass(frozen=True, slots=True)
class TemporalFold:
    """One expanding-window temporal CV fold, expressed in complete quarters."""

    index: int
    train_quarters: tuple[str, ...]
    validation_quarters: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "train_quarters": list(self.train_quarters),
            "validation_quarters": list(self.validation_quarters),
        }


@dataclass(frozen=True, slots=True)
class FoldEvaluation:
    """Metrics for one candidate on one expanding-window validation block."""

    fold: TemporalFold
    metrics: ClassificationMetrics

    def to_dict(self) -> dict[str, Any]:
        return {"fold": self.fold.to_dict(), "metrics": self.metrics.to_dict()}


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """All temporal-CV evidence for one deterministic parameter candidate."""

    index: int
    parameters: Mapping[str, Any]
    folds: tuple[FoldEvaluation, ...]
    mean_metrics: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "parameters": _json_safe(self.parameters),
            "folds": [fold.to_dict() for fold in self.folds],
            "mean_metrics": dict(self.mean_metrics),
        }


@dataclass(frozen=True, slots=True)
class CrossValidationResult:
    """Candidate comparison selected strictly from expanding training folds."""

    model_name: str
    folds: tuple[TemporalFold, ...]
    candidates: tuple[CandidateEvaluation, ...]
    selected_index: int

    @property
    def selected_candidate(self) -> CandidateEvaluation:
        return self.candidates[self.selected_index]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "strategy": "expanding_window_by_complete_issue_quarter",
            "selection_metric": "mean_roc_auc_then_pr_auc_then_f1",
            "folds": [fold.to_dict() for fold in self.folds],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_index": self.selected_index,
            "selected_parameters": _json_safe(self.selected_candidate.parameters),
        }


@dataclass(frozen=True, slots=True)
class ModelEvaluation:
    """Final fit plus validation-selected threshold and untouched shift metrics."""

    model_name: str
    feature_view: str
    cross_validation: CrossValidationResult
    threshold_selection: ThresholdSelection
    validation_metrics: ClassificationMetrics
    shift_metrics: ClassificationMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "feature_view": self.feature_view,
            "cross_validation": self.cross_validation.to_dict(),
            "threshold_selection": self.threshold_selection.to_dict(),
            "validation_metrics": self.validation_metrics.to_dict(),
            "shift_metrics": self.shift_metrics.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ModelTrainingResult:
    """Stable artifact locations and evaluation evidence from a complete run."""

    root: Path
    model_version: str
    metadata_path: Path
    feature_schema_path: Path
    metrics_path: Path
    detector_path: Path
    explainer_path: Path
    model_paths: Mapping[str, Path]
    evaluations: Mapping[str, ModelEvaluation]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.root),
            "model_version": self.model_version,
            "metadata_path": str(self.metadata_path),
            "feature_schema_path": str(self.feature_schema_path),
            "metrics_path": str(self.metrics_path),
            "detector_path": str(self.detector_path),
            "explainer_path": str(self.explainer_path),
            "model_paths": {name: str(path) for name, path in self.model_paths.items()},
            "models": {name: result.to_dict() for name, result in self.evaluations.items()},
        }


def expanding_window_folds(
    training_frame: pd.DataFrame,
    *,
    cv_splits: int,
    quarter_column: str = ISSUE_QUARTER_COLUMN,
    date_column: str = ISSUE_DATE_COLUMN,
) -> tuple[TemporalFold, ...]:
    """Divide training quarters into chronological expanding train/validation folds."""

    if not isinstance(training_frame, pd.DataFrame) or training_frame.empty:
        raise ModelingDataError("Expanding CV requires a non-empty training DataFrame.")
    if isinstance(cv_splits, bool) or not isinstance(cv_splits, Integral) or cv_splits < 1:
        raise ModelingDataError("cv_splits must be a positive integer.")
    missing = [column for column in (quarter_column, date_column) if column not in training_frame]
    if missing:
        raise ModelingDataError(f"Expanding CV training data is missing columns: {missing}")

    dates = pd.to_datetime(training_frame[date_column], errors="coerce", utc=True)
    if dates.isna().any():
        raise ModelingDataError("Expanding CV training data contains invalid issue dates.")
    quarter_values = training_frame[quarter_column].astype(str)
    if quarter_values.str.len().eq(0).any():
        raise ModelingDataError("Expanding CV training data contains empty issue-quarter values.")
    quarter_dates = pd.DataFrame({"quarter": quarter_values, "date": dates}).groupby(
        "quarter", sort=False, observed=True
    )["date"].min()
    ordered_quarters = tuple(
        quarter_dates.sort_values(kind="stable").index.astype(str).tolist()
    )
    required_quarters = int(cv_splits) + 1
    if len(ordered_quarters) < required_quarters:
        raise ModelingDataError(
            "Expanding CV requires at least cv_splits + 1 distinct training quarters; "
            f"found {len(ordered_quarters)} for cv_splits={cv_splits}."
        )

    blocks = np.array_split(np.asarray(ordered_quarters, dtype=object), int(cv_splits) + 1)
    folds: list[TemporalFold] = []
    for index in range(1, len(blocks)):
        train_quarters = tuple(item for block in blocks[:index] for item in block.tolist())
        validation_quarters = tuple(blocks[index].tolist())
        # Defensive; array_split above prevents either side being empty.
        if not train_quarters or not validation_quarters:
            raise ModelingDataError("Expanding CV produced an empty train or validation window.")
        folds.append(
            TemporalFold(
                index=index,
                train_quarters=train_quarters,
                validation_quarters=validation_quarters,
            )
        )
    return tuple(folds)


def _labels(frame: pd.DataFrame) -> np.ndarray:
    if TARGET_COLUMN not in frame:
        raise ModelingDataError(f"Modeling frame is missing {TARGET_COLUMN!r}.")
    target = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce")
    if target.isna().any():
        raise ModelingDataError("Modeling frame target contains missing or non-numeric values.")
    values = target.to_numpy(dtype=np.int8)
    if set(values.tolist()) != {0, 1}:
        raise ModelingDataError("Each modeled temporal window must contain both target classes.")
    return values


def _features(frame: pd.DataFrame, feature_names: tuple[str, ...]) -> pd.DataFrame:
    missing = [name for name in feature_names if name not in frame]
    if missing:
        raise ModelingDataError(f"Modeling frame is missing model features: {missing}")
    values = frame.loc[:, feature_names]
    try:
        numeric = values.astype(np.float64)
    except (TypeError, ValueError) as exc:
        raise ModelingDataError("Modeling features must be numeric.") from exc
    if not np.isfinite(numeric.to_numpy()).all():
        raise ModelingDataError("Modeling features must be finite.")
    return numeric


def _frame_for_quarters(frame: pd.DataFrame, quarters: tuple[str, ...]) -> pd.DataFrame:
    subset = frame.loc[frame[ISSUE_QUARTER_COLUMN].astype(str).isin(quarters)].copy()
    if subset.empty:
        raise ModelingDataError("An expanding CV quarter window unexpectedly contains no rows.")
    return subset.sort_values(ISSUE_DATE_COLUMN, kind="stable").reset_index(drop=True)


def _mean_metrics(folds: tuple[FoldEvaluation, ...]) -> dict[str, float]:
    if not folds:
        raise ModelingDataError("Cannot calculate mean metrics for zero cross-validation folds.")
    names = ("accuracy", "roc_auc", "pr_auc", "f1", "ks", "brier")
    return {
        name: float(np.mean([getattr(fold.metrics, name) for fold in folds])) for name in names
    }


def cross_validate_model_candidates(
    model_name: str,
    training_frame: pd.DataFrame,
    *,
    feature_names: tuple[str, ...],
    candidates: Sequence[Mapping[str, Any]],
    cv_splits: int,
    random_seed: int,
    model_factories: Mapping[str, EstimatorFactory] | None = None,
) -> CrossValidationResult:
    """Evaluate parameter candidates on expanding training-quarter windows only."""

    if model_name not in MODEL_NAMES:
        raise ModelingDataError(f"model_name must be one of {MODEL_NAMES}; got {model_name!r}.")
    folds = expanding_window_folds(training_frame, cv_splits=cv_splits)
    normalised_candidates = _normalise_candidates(candidates, field_name="candidates")
    candidate_results: list[CandidateEvaluation] = []
    for candidate_index, parameters in enumerate(normalised_candidates):
        fold_results: list[FoldEvaluation] = []
        for fold in folds:
            fold_train = _frame_for_quarters(training_frame, fold.train_quarters)
            fold_validation = _frame_for_quarters(training_frame, fold.validation_quarters)
            train_target = _labels(fold_train)
            validation_target = _labels(fold_validation)
            estimator = create_estimator(
                model_name,
                parameters,
                random_seed=int(random_seed),
                labels=train_target,
                factories=model_factories,
            )
            try:
                estimator.fit(_features(fold_train, feature_names), train_target)
            except (TypeError, ValueError, RuntimeError) as exc:
                raise ModelingError(
                    f"{model_name} failed during expanding CV candidate {candidate_index}, "
                    f"fold {fold.index}: {exc}"
                ) from exc
            scores = positive_class_probabilities(
                estimator,
                _features(fold_validation, feature_names),
            )
            # A fixed threshold is used inside CV; the deployable threshold is
            # selected once, later, from the untouched validation split.
            metrics = evaluate_binary_predictions(
                validation_target,
                scores,
                threshold=0.5,
                split_name=f"expanding CV fold {fold.index}",
            )
            fold_results.append(FoldEvaluation(fold=fold, metrics=metrics))
        fold_tuple = tuple(fold_results)
        candidate_results.append(
            CandidateEvaluation(
                index=candidate_index,
                parameters=parameters,
                folds=fold_tuple,
                mean_metrics=_mean_metrics(fold_tuple),
            )
        )

    selected = max(
        candidate_results,
        key=lambda candidate: (
            candidate.mean_metrics["roc_auc"],
            candidate.mean_metrics["pr_auc"],
            candidate.mean_metrics["f1"],
            -candidate.index,
        ),
    )
    return CrossValidationResult(
        model_name=model_name,
        folds=folds,
        candidates=tuple(candidate_results),
        selected_index=selected.index,
    )


def _quarters(frame: pd.DataFrame) -> tuple[str, ...]:
    return tuple(dict.fromkeys(frame[ISSUE_QUARTER_COLUMN].astype(str).tolist()))


def _window_metadata(frame: pd.DataFrame, *, split_name: str) -> dict[str, Any]:
    dates = pd.to_datetime(frame[ISSUE_DATE_COLUMN], errors="raise", utc=True)
    return {
        "split": split_name,
        "quarters": list(_quarters(frame)),
        "row_count": int(len(frame)),
        "issue_date_min": dates.min().isoformat(),
        "issue_date_max": dates.max().isoformat(),
    }


def _model_version(
    *,
    dataset: ModelingDataset,
    config: TrainingConfig,
    evaluations: Mapping[str, ModelEvaluation],
    training_frame: pd.DataFrame,
    schema_sha256: str,
) -> str:
    payload = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "primary_model": PRIMARY_MODEL_NAME,
        "feature_schema_sha256": schema_sha256,
        "source_manifest_sha256": dataset.manifest_sha256,
        "random_seed": config.random_seed,
        "training_quarters": list(_quarters(training_frame)),
        "selected_parameters": {
            name: result.cross_validation.selected_candidate.parameters
            for name, result in evaluations.items()
        },
    }
    return f"s2-{_sha256_bytes(_canonical_json(payload))[:16]}"


def _artifact_name(model_name: str) -> str:
    return {
        "lightgbm": "model.joblib",
        "xgboost": "xgboost_model.joblib",
        "logistic_regression": "logistic_regression_model.joblib",
    }[model_name]


def _write_training_artifacts(
    *,
    output_dir: str | Path,
    overwrite: bool,
    dataset: ModelingDataset,
    config: TrainingConfig,
    estimators: Mapping[str, Any],
    adwin_detector: object,
    shap_explainer: object,
    evaluations: Mapping[str, ModelEvaluation],
    training_frame: pd.DataFrame,
    validation_frame: pd.DataFrame,
    shift_frame: pd.DataFrame,
) -> ModelTrainingResult:
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists() and not overwrite:
        raise ModelingError(
            f"Model artifact destination already exists: {destination}. "
            "Pass overwrite=True to replace it."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        feature_schema = {
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "feature_names": list(dataset.feature_names),
            "feature_schema_sha256": _feature_schema_sha256(dataset.feature_names),
        }
        feature_schema_bytes = _canonical_json(feature_schema)
        feature_schema_sha256 = _feature_schema_sha256(dataset.feature_names)
        (staging / "feature_schema.json").write_bytes(feature_schema_bytes)
        feature_schema_file_sha256 = _sha256_file(staging / "feature_schema.json")

        model_paths: dict[str, Path] = {}
        model_artifacts: dict[str, dict[str, Any]] = {}
        for model_name in MODEL_NAMES:
            if model_name not in estimators or model_name not in evaluations:
                raise ModelingError(f"Missing trained {model_name!r} model or evaluation.")
            relative_name = _artifact_name(model_name)
            artifact_path = staging / relative_name
            joblib.dump(estimators[model_name], artifact_path, compress=3, protocol=4)
            model_paths[model_name] = artifact_path
            model_artifacts[model_name] = {
                "artifact": relative_name,
                "sha256": _sha256_file(artifact_path),
                "feature_view": evaluations[model_name].feature_view,
                "selected_parameters": _json_safe(
                    evaluations[model_name].cross_validation.selected_candidate.parameters
                ),
                "threshold": evaluations[model_name].threshold_selection.threshold,
            }

        detector_path = staging / "adwin_detector.joblib"
        joblib.dump(adwin_detector, detector_path, compress=3, protocol=4)
        explainer_path = staging / "shap_explainer.joblib"
        joblib.dump(shap_explainer, explainer_path, compress=3, protocol=4)

        metrics_payload = {
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "threshold_policy": "selected_from_validation_only_by_f1",
            "models": {name: evaluations[name].to_dict() for name in MODEL_NAMES},
        }
        metrics_bytes = _canonical_json(metrics_payload)
        metrics_path = staging / "metrics.json"
        metrics_path.write_bytes(metrics_bytes)

        model_version = _model_version(
            dataset=dataset,
            config=config,
            evaluations=evaluations,
            training_frame=training_frame,
            schema_sha256=feature_schema_sha256,
        )
        metadata = {
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "model_version": model_version,
            "primary_model": PRIMARY_MODEL_NAME,
            "model_artifact": _artifact_name(PRIMARY_MODEL_NAME),
            "model_artifact_sha256": model_artifacts[PRIMARY_MODEL_NAME]["sha256"],
            "feature_schema_artifact": "feature_schema.json",
            "feature_schema_sha256": feature_schema_sha256,
            "feature_schema_file_sha256": feature_schema_file_sha256,
            "feature_names": list(dataset.feature_names),
            "metrics_artifact": "metrics.json",
            "metrics_sha256": _sha256_bytes(metrics_bytes),
            "threshold": evaluations[PRIMARY_MODEL_NAME].threshold_selection.threshold,
            "prediction_threshold": evaluations[PRIMARY_MODEL_NAME].threshold_selection.threshold,
            "threshold_source": "validation_only_f1",
            "feature_view": evaluations[PRIMARY_MODEL_NAME].feature_view,
            "random_seed": config.random_seed,
            "synthetic_demo": config.synthetic_demo,
            "source_feature_store": str(dataset.root),
            "source_feature_store_manifest_sha256": dataset.manifest_sha256,
            "training_window": _window_metadata(training_frame, split_name="train"),
            "validation_window": _window_metadata(validation_frame, split_name="validation"),
            "shift_window": _window_metadata(shift_frame, split_name="shift"),
            "temporal_cross_validation": {
                "strategy": "expanding_window_by_complete_issue_quarter",
                "cv_splits": config.cv_splits,
                "selection_metric": "mean_roc_auc_then_pr_auc_then_f1",
                "preprocessing_note": (
                    "The Sprint 1 feature store freezes preprocessing state fitted on its full "
                    "training window. Expanding CV evaluates chronological model fits on that "
                    "frozen representation; a fully nested preprocessing study requires raw-data "
                    "rebuilds per fold."
                ),
            },
            "models": model_artifacts,
            "adwin_detector_artifact": "adwin_detector.joblib",
            "adwin_detector_sha256": _sha256_file(detector_path),
            "shap_explainer_artifact": "shap_explainer.joblib",
            "shap_explainer_sha256": _sha256_file(explainer_path),
            "shap_explainer_model": PRIMARY_MODEL_NAME,
            "adwin_calibration": {
                "source": "primary_model_validation_score_stream_only",
                "delta": 0.002,
                "row_count": int(len(validation_frame)),
            },
        }
        metadata_path = staging / "metadata.json"
        metadata_path.write_bytes(_canonical_json(metadata))

        if destination.exists():
            shutil.rmtree(destination)
        os.replace(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    resolved_paths = {
        name: destination / path.name for name, path in model_paths.items()
    }
    return ModelTrainingResult(
        root=destination,
        model_version=model_version,
        metadata_path=destination / "metadata.json",
        feature_schema_path=destination / "feature_schema.json",
        metrics_path=destination / "metrics.json",
        detector_path=destination / "adwin_detector.joblib",
        explainer_path=destination / "shap_explainer.joblib",
        model_paths=resolved_paths,
        evaluations=dict(evaluations),
    )


def train_sprint2_models(
    feature_store: str | Path,
    output_dir: str | Path,
    *,
    config: TrainingConfig | None = None,
    overwrite: bool = False,
    model_factories: Mapping[str, EstimatorFactory] | None = None,
    explainer_factory: Callable[[Any], Any] | None = None,
) -> ModelTrainingResult:
    """Train, compare, evaluate, and persist Sprint 2 models from the feature store.

    Tree models always use the unscaled feature view. The logistic-regression
    baseline always uses Sprint 1's scaled view. Candidate selection uses only
    expanding folds within the training window; the operating threshold is then
    selected only on the next validation window and reused unchanged for the
    held-out shift evaluation.
    """

    resolved_config = config if config is not None else TrainingConfig()
    if not isinstance(resolved_config, TrainingConfig):
        raise ModelingDataError("config must be a TrainingConfig or None.")
    dataset = load_modeling_dataset(feature_store)
    estimators: dict[str, Any] = {}
    evaluations: dict[str, ModelEvaluation] = {}
    primary_training_frame: pd.DataFrame | None = None
    primary_validation_frame: pd.DataFrame | None = None
    primary_shift_frame: pd.DataFrame | None = None
    primary_validation_scores: np.ndarray | None = None

    for model_name in MODEL_NAMES:
        feature_view = "scaled" if model_name == "logistic_regression" else "unscaled"
        training_frame = dataset.split_frame("train", feature_view=feature_view)
        validation_frame = dataset.split_frame("validation", feature_view=feature_view)
        shift_frame = dataset.split_frame("shift", feature_view=feature_view)
        cross_validation = cross_validate_model_candidates(
            model_name,
            training_frame,
            feature_names=dataset.feature_names,
            candidates=resolved_config.candidates_for(model_name),
            cv_splits=resolved_config.cv_splits,
            random_seed=resolved_config.random_seed,
            model_factories=model_factories,
        )
        train_target = _labels(training_frame)
        estimator = create_estimator(
            model_name,
            cross_validation.selected_candidate.parameters,
            random_seed=resolved_config.random_seed,
            labels=train_target,
            factories=model_factories,
        )
        try:
            estimator.fit(_features(training_frame, dataset.feature_names), train_target)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise ModelingError(f"{model_name} failed during final training: {exc}") from exc

        validation_target = _labels(validation_frame)
        validation_scores = positive_class_probabilities(
            estimator,
            _features(validation_frame, dataset.feature_names),
        )
        threshold_selection = select_validation_threshold(validation_target, validation_scores)
        validation_metrics = threshold_selection.validation_metrics
        shift_target = _labels(shift_frame)
        shift_scores = positive_class_probabilities(
            estimator,
            _features(shift_frame, dataset.feature_names),
        )
        shift_metrics = evaluate_binary_predictions(
            shift_target,
            shift_scores,
            threshold=threshold_selection.threshold,
            split_name="held-out shift split",
        )
        estimators[model_name] = estimator
        evaluations[model_name] = ModelEvaluation(
            model_name=model_name,
            feature_view=feature_view,
            cross_validation=cross_validation,
            threshold_selection=threshold_selection,
            validation_metrics=validation_metrics,
            shift_metrics=shift_metrics,
        )
        if model_name == PRIMARY_MODEL_NAME:
            primary_training_frame = training_frame
            primary_validation_frame = validation_frame
            primary_shift_frame = shift_frame
            primary_validation_scores = validation_scores

    if (
        primary_training_frame is None
        or primary_validation_frame is None
        or primary_shift_frame is None
        or primary_validation_scores is None
    ):
        raise ModelingError("Primary model training did not produce all temporal windows.")
    adwin_detector = calibrate_adwin_detector(primary_validation_scores)
    if explainer_factory is None:
        shap_explainer = create_tree_explainer(estimators[PRIMARY_MODEL_NAME])
    else:
        try:
            shap_explainer = explainer_factory(estimators[PRIMARY_MODEL_NAME])
        except (TypeError, ValueError, AttributeError) as exc:
            raise ModelingError(f"Custom SHAP explainer factory failed: {exc}") from exc
    return _write_training_artifacts(
        output_dir=output_dir,
        overwrite=overwrite,
        dataset=dataset,
        config=resolved_config,
        estimators=estimators,
        adwin_detector=adwin_detector,
        shap_explainer=shap_explainer,
        evaluations=evaluations,
        training_frame=primary_training_frame,
        validation_frame=primary_validation_frame,
        shift_frame=primary_shift_frame,
    )
