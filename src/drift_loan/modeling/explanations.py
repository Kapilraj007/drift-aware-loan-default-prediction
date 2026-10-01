"""Persisted TreeSHAP construction and normalized transformed-feature attributions."""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np
import pandas as pd

from .errors import ModelingDataError, ModelingDependencyError


def create_tree_explainer(model: Any) -> Any:
    """Create the exact TreeSHAP explainer for the trained LightGBM primary model."""

    try:
        shap = importlib.import_module("shap")
    except ImportError as exc:
        raise ModelingDependencyError(
            "shap is required to create the Sprint 2 TreeExplainer artifact."
        ) from exc
    try:
        return shap.TreeExplainer(model)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ModelingDataError(
            f"Unable to create a SHAP TreeExplainer for the primary model: {exc}"
        ) from exc


def explain_transformed_features(
    explainer: Any,
    features: pd.DataFrame,
) -> np.ndarray:
    """Return class-1 SHAP values in the same row/feature order as ``features``."""

    if not isinstance(features, pd.DataFrame) or features.empty:
        raise ModelingDataError("SHAP explanations require a non-empty pandas DataFrame.")
    if not hasattr(explainer, "shap_values"):
        raise ModelingDataError("Persisted SHAP explainer does not provide shap_values().")
    try:
        raw_values = explainer.shap_values(features, check_additivity=False)
    except TypeError:
        # Some supported SHAP versions do not expose check_additivity here.
        raw_values = explainer.shap_values(features)
    except (ValueError, AttributeError, RuntimeError) as exc:
        raise ModelingDataError(f"SHAP explanation failed: {exc}") from exc

    if isinstance(raw_values, list):
        if len(raw_values) != 2:
            raise ModelingDataError(
                "Binary SHAP list output must contain exactly negative and positive-class values."
            )
        values = np.asarray(raw_values[1], dtype=np.float64)
    else:
        values = np.asarray(raw_values, dtype=np.float64)
        if values.ndim == 3 and values.shape[-1] == 2:
            values = values[:, :, 1]
    expected_shape = (len(features), features.shape[1])
    if values.shape != expected_shape:
        raise ModelingDataError(
            "SHAP values do not match the transformed feature matrix shape: "
            f"expected {expected_shape}, found {values.shape}."
        )
    if not np.isfinite(values).all():
        raise ModelingDataError("SHAP values contain non-finite values.")
    return values
