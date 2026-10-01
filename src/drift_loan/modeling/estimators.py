"""Estimator factories and model-family-neutral probability handling."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression

from .errors import ModelingDataError, ModelingDependencyError

MODEL_NAMES: tuple[str, ...] = ("lightgbm", "xgboost", "logistic_regression")
EstimatorFactory = Callable[[Mapping[str, Any], int, np.ndarray], Any]


def _optional_module(module_name: str, *, package_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ModelingDependencyError(
            f"{package_name} is required to train or load the requested model family. "
            f"Install the Sprint 2 dependencies before continuing."
        ) from exc


def _validate_training_labels(labels: object) -> np.ndarray:
    values = np.asarray(labels).reshape(-1)
    if values.size == 0:
        raise ModelingDataError("Estimator training labels must not be empty.")
    try:
        target = values.astype(np.int8)
    except (TypeError, ValueError) as exc:
        raise ModelingDataError("Estimator training labels must be binary 0/1 values.") from exc
    if not np.array_equal(values, target) or set(target.tolist()) != {0, 1}:
        raise ModelingDataError(
            "Estimator training labels must contain both binary classes 0 and 1."
        )
    return target


def create_lightgbm_estimator(
    parameters: Mapping[str, Any],
    random_seed: int,
    labels: np.ndarray,
) -> Any:
    """Create a deterministic, class-balanced LightGBM classifier."""

    _validate_training_labels(labels)
    lightgbm = _optional_module("lightgbm", package_name="lightgbm")
    defaults: dict[str, Any] = {
        "objective": "binary",
        "n_estimators": 200,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_child_samples": 30,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "class_weight": "balanced",
        "random_state": int(random_seed),
        "n_jobs": 1,
        "deterministic": True,
        "force_col_wise": True,
        "verbosity": -1,
    }
    defaults.update(dict(parameters))
    return lightgbm.LGBMClassifier(**defaults)


def create_xgboost_estimator(
    parameters: Mapping[str, Any],
    random_seed: int,
    labels: np.ndarray,
) -> Any:
    """Create a deterministic XGBoost robustness-check classifier."""

    target = _validate_training_labels(labels)
    xgboost = _optional_module("xgboost", package_name="xgboost")
    positive_count = int(target.sum())
    negative_count = int((1 - target).sum())
    defaults: dict[str, Any] = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "n_estimators": 120,
        "learning_rate": 0.05,
        "max_depth": 5,
        "min_child_weight": 5,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "scale_pos_weight": negative_count / positive_count,
        "random_state": int(random_seed),
        "n_jobs": 1,
        "tree_method": "hist",
    }
    defaults.update(dict(parameters))
    return xgboost.XGBClassifier(**defaults)


def create_logistic_regression_estimator(
    parameters: Mapping[str, Any],
    random_seed: int,
    labels: np.ndarray,
) -> LogisticRegression:
    """Create the L2-regularized scaled-feature interpretability baseline."""

    _validate_training_labels(labels)
    defaults: dict[str, Any] = {
        "penalty": "l2",
        "C": 1.0,
        "solver": "lbfgs",
        "max_iter": 1_000,
        "class_weight": "balanced",
        "random_state": int(random_seed),
    }
    defaults.update(dict(parameters))
    return LogisticRegression(**defaults)


def create_estimator(
    model_name: str,
    parameters: Mapping[str, Any],
    *,
    random_seed: int,
    labels: np.ndarray,
    factories: Mapping[str, EstimatorFactory] | None = None,
) -> Any:
    """Create one estimator, permitting dependency-free test doubles."""

    if model_name not in MODEL_NAMES:
        raise ModelingDataError(f"model_name must be one of {MODEL_NAMES}; got {model_name!r}.")
    validated_labels = _validate_training_labels(labels)
    if factories is not None and model_name in factories:
        return factories[model_name](parameters, int(random_seed), validated_labels)
    factory_by_name: dict[str, EstimatorFactory] = {
        "lightgbm": create_lightgbm_estimator,
        "xgboost": create_xgboost_estimator,
        "logistic_regression": create_logistic_regression_estimator,
    }
    return factory_by_name[model_name](parameters, int(random_seed), validated_labels)


def positive_class_probabilities(estimator: Any, features: object) -> np.ndarray:
    """Return the class-1 probability, regardless of estimator class ordering."""

    if not hasattr(estimator, "predict_proba"):
        raise ModelingDataError("Estimator does not provide predict_proba().")
    try:
        raw_probabilities = np.asarray(estimator.predict_proba(features), dtype=np.float64)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ModelingDataError(f"Estimator failed to produce probabilities: {exc}") from exc
    if raw_probabilities.ndim != 2 or raw_probabilities.shape[0] == 0:
        raise ModelingDataError("Estimator predict_proba() must return a non-empty 2D array.")

    classes = np.asarray(getattr(estimator, "classes_", []))
    matching = np.flatnonzero(classes == 1)
    if matching.size == 1:
        class_index = int(matching[0])
    elif raw_probabilities.shape[1] == 2:
        class_index = 1
    else:
        raise ModelingDataError(
            "Estimator probabilities do not expose a uniquely identifiable positive class 1."
        )
    if class_index >= raw_probabilities.shape[1]:
        raise ModelingDataError("Estimator positive-class index exceeds predict_proba() width.")

    values = raw_probabilities[:, class_index]
    if not np.isfinite(values).all() or np.any(values < 0.0) or np.any(values > 1.0):
        raise ModelingDataError("Estimator returned non-finite or out-of-range probabilities.")
    return values.astype(np.float64, copy=False)
