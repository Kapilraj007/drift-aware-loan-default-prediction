"""Lazy SHAP explanations and short, officer-readable narratives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .inference_service import InferenceResult


@dataclass(frozen=True, slots=True)
class FeatureAttribution:
    feature: str
    display_name: str
    contribution: float
    direction: str
    feature_value: float | int | str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature,
            "display_name": self.display_name,
            "contribution": self.contribution,
            "direction": self.direction,
            "feature_value": self.feature_value,
        }


@dataclass(frozen=True, slots=True)
class Explanation:
    available: bool
    narrative: str
    top_features: tuple[FeatureAttribution, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "narrative": self.narrative,
            "top_features": [item.to_dict() for item in self.top_features],
        }


_DISPLAY_NAMES = {
    "annual_inc": "annual income",
    "dti": "debt-to-income ratio",
    "int_rate": "interest rate",
    "loan_amnt": "loan amount",
    "loan_to_income": "loan-to-income ratio",
    "installment_to_income": "installment-to-income ratio",
    "credit_history_years": "credit history length",
    "revol_util": "revolving credit utilization",
    "revol_bal": "revolving balance",
    "emp_length": "employment length",
    "grade": "loan grade",
    "sub_grade": "loan sub-grade",
}


def _display_name(feature: str) -> str:
    if feature in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[feature]
    return feature.replace("_was_missing", " missingness").replace("_", " ")


def _class_one_values(values: Any) -> np.ndarray:
    """Normalize SHAP's varying binary-class return formats to one row."""

    if isinstance(values, list):
        if len(values) < 2:
            raise ValueError("Binary SHAP output did not include a positive class")
        values = values[1]
    array = np.asarray(values, dtype="float64")
    if array.ndim == 1:
        return array
    if array.ndim == 2:
        return array[0]
    if array.ndim == 3:
        # SHAP's current Explanation commonly has (rows, features, classes).
        return array[0, :, 1]
    raise ValueError(f"Unsupported SHAP output shape: {array.shape}")


class ShapService:
    """Creates explainers only after a model has successfully been scored."""

    def __init__(self) -> None:
        self._explainers: dict[int, Any] = {}

    def _values(self, result: InferenceResult) -> np.ndarray:
        predictor = result.artifact.predictor
        if hasattr(predictor, "shap_values"):
            return _class_one_values(predictor.shap_values(result.model_features))

        persisted_explainer = getattr(predictor, "shap_explainer", None)
        if persisted_explainer is not None:
            try:
                output = persisted_explainer.shap_values(
                    result.model_features,
                    check_additivity=False,
                )
            except TypeError:
                output = persisted_explainer.shap_values(result.model_features)
            return _class_one_values(output)

        model = getattr(predictor, "model", predictor)
        key = id(model)
        explainer = self._explainers.get(key)
        if explainer is None:
            import shap  # Imported only when explanations are actually requested.

            explainer = shap.TreeExplainer(model)
            self._explainers[key] = explainer
        output = explainer(result.model_features)
        values = getattr(output, "values", output)
        return _class_one_values(values)

    def explain(self, result: InferenceResult, *, top_k: int = 5) -> Explanation:
        """Return signed top attributions or an explicit availability message."""

        try:
            values = self._values(result)
        except (ImportError, ModuleNotFoundError):
            return Explanation(
                available=False,
                narrative=(
                    "A model score is available, but its SHAP explanation dependency "
                    "is unavailable."
                ),
            )
        except Exception:
            # Do not turn a valid human-review score into an outage because an
            # optional explanation artifact is incompatible.  The response is
            # explicit and persisted for auditability.
            return Explanation(
                available=False,
                narrative=(
                    "A model score is available, but an explanation could not be generated "
                    "for it."
                ),
            )

        row = result.model_features.iloc[0]
        if len(values) != len(row.index):
            return Explanation(
                available=False,
                narrative=(
                    "A model score is available, but the explanation feature schema is "
                    "incompatible."
                ),
            )
        order = np.argsort(np.abs(values))[::-1][: max(1, top_k)]
        attributions: list[FeatureAttribution] = []
        for position in order:
            feature = str(row.index[position])
            raw_value = row.iloc[position]
            if isinstance(raw_value, np.generic):
                raw_value = raw_value.item()
            value = raw_value if isinstance(raw_value, float | int | str) else None
            contribution = float(values[position])
            attributions.append(
                FeatureAttribution(
                    feature=feature,
                    display_name=_display_name(feature),
                    contribution=contribution,
                    direction="risk_increasing" if contribution >= 0 else "risk_reducing",
                    feature_value=value,
                )
            )

        increases = [item.display_name for item in attributions if item.contribution >= 0]
        reduces = [item.display_name for item in attributions if item.contribution < 0]
        if increases:
            narrative = "Elevated risk is driven primarily by " + ", ".join(increases) + "."
        elif reduces:
            narrative = "The score is reduced primarily by " + ", ".join(reduces) + "."
        else:  # pragma: no cover - zero SHAP values are rare but valid
            narrative = "No individual feature materially changed this model score."
        return Explanation(available=True, narrative=narrative, top_features=tuple(attributions))
