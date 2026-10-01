"""Binary-classification evaluation and validation-only threshold selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

from .errors import ModelingDataError


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    """Metrics for one binary split at one already-selected operating threshold.

    ``pr_auc`` is average precision, the conventional summary used for an
    imbalanced binary classifier. ``ks`` is the maximum TPR minus FPR over the
    ROC curve, rather than a significance-test p-value.
    """

    accuracy: float
    roc_auc: float
    pr_auc: float
    f1: float
    precision: float
    recall: float
    ks: float
    brier: float
    threshold: float
    row_count: int
    positive_count: int
    negative_count: int
    true_negative: int
    false_positive: int
    false_negative: int
    true_positive: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ThresholdSelection:
    """A threshold selected exclusively from validation probabilities."""

    threshold: float
    objective: str
    objective_value: float
    candidate_count: int
    validation_metrics: ClassificationMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "objective": self.objective,
            "objective_value": self.objective_value,
            "candidate_count": self.candidate_count,
            "validation_metrics": self.validation_metrics.to_dict(),
        }


def _binary_labels(values: object, *, name: str = "labels") -> np.ndarray:
    labels = np.asarray(values).reshape(-1)
    if labels.size == 0:
        raise ModelingDataError(f"{name} must not be empty.")
    try:
        numeric = labels.astype(np.int8)
    except (TypeError, ValueError) as exc:
        raise ModelingDataError(f"{name} must contain binary 0/1 values.") from exc
    if not np.array_equal(labels, numeric):
        raise ModelingDataError(f"{name} must contain binary 0/1 values.")
    unexpected = sorted(set(numeric.tolist()) - {0, 1})
    if unexpected:
        raise ModelingDataError(f"{name} must contain only 0 and 1; found {unexpected}.")
    return numeric


def _probabilities(values: object, *, expected_rows: int | None = None) -> np.ndarray:
    try:
        probabilities = np.asarray(values, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise ModelingDataError(
            "Predicted probabilities must be a numeric one-dimensional array."
        ) from exc
    if probabilities.size == 0:
        raise ModelingDataError("Predicted probabilities must not be empty.")
    if expected_rows is not None and probabilities.size != expected_rows:
        raise ModelingDataError(
            "Predicted probability count does not match the label count: "
            f"{probabilities.size} != {expected_rows}."
        )
    if not np.isfinite(probabilities).all():
        raise ModelingDataError("Predicted probabilities must all be finite.")
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise ModelingDataError(
            "Predicted probabilities must lie in the inclusive [0, 1] interval."
        )
    return probabilities


def _require_both_classes(labels: np.ndarray, *, split_name: str) -> None:
    present = set(labels.tolist())
    if present != {0, 1}:
        raise ModelingDataError(
            f"{split_name} must contain both target classes to calculate AUC and KS; "
            f"found {sorted(present)}."
        )


def evaluate_binary_predictions(
    labels: object,
    probabilities: object,
    *,
    threshold: float,
    split_name: str = "evaluation split",
) -> ClassificationMetrics:
    """Calculate the project-standard binary-classification metrics.

    The caller supplies the threshold rather than allowing this function to
    optimize it. That makes it safe to evaluate the held-out shift split using
    a threshold selected earlier on the validation split.
    """

    if not isinstance(threshold, float | int | np.floating | np.integer):
        raise ModelingDataError("threshold must be a finite number in [0, 1].")
    resolved_threshold = float(threshold)
    if not np.isfinite(resolved_threshold) or not 0.0 <= resolved_threshold <= 1.0:
        raise ModelingDataError("threshold must be a finite number in [0, 1].")

    target = _binary_labels(labels)
    scores = _probabilities(probabilities, expected_rows=len(target))
    _require_both_classes(target, split_name=split_name)
    predictions = (scores >= resolved_threshold).astype(np.int8)
    false_positive_rate, true_positive_rate, _ = roc_curve(target, scores)
    true_negative, false_positive, false_negative, true_positive = confusion_matrix(
        target,
        predictions,
        labels=(0, 1),
    ).ravel()

    return ClassificationMetrics(
        accuracy=float(accuracy_score(target, predictions)),
        roc_auc=float(roc_auc_score(target, scores)),
        pr_auc=float(average_precision_score(target, scores)),
        f1=float(f1_score(target, predictions, zero_division=0)),
        precision=float(precision_score(target, predictions, zero_division=0)),
        recall=float(recall_score(target, predictions, zero_division=0)),
        ks=float(np.max(true_positive_rate - false_positive_rate)),
        brier=float(brier_score_loss(target, scores)),
        threshold=resolved_threshold,
        row_count=int(len(target)),
        positive_count=int(target.sum()),
        negative_count=int((1 - target).sum()),
        true_negative=int(true_negative),
        false_positive=int(false_positive),
        false_negative=int(false_negative),
        true_positive=int(true_positive),
    )


def select_validation_threshold(
    labels: object,
    probabilities: object,
    *,
    objective: str = "f1",
) -> ThresholdSelection:
    """Choose a deterministic operating threshold using validation data only.

    The current project policy optimizes F1 on thresholds emitted by
    ``precision_recall_curve``. In a tie, the threshold closest to 0.5 wins,
    then the lower threshold; both choices are deterministic and recorded in
    the artifact metadata.
    """

    if objective != "f1":
        raise ModelingDataError("Only the validation threshold objective 'f1' is supported.")
    target = _binary_labels(labels, name="validation labels")
    scores = _probabilities(probabilities, expected_rows=len(target))
    _require_both_classes(target, split_name="validation split")

    precision, recall, thresholds = precision_recall_curve(target, scores)
    if thresholds.size == 0:
        # This can only occur for pathological inputs, but preserves an
        # explicit deterministic fallback instead of guessing from a holdout.
        selected = 0.5
    else:
        f1_values = np.divide(
            2.0 * precision[:-1] * recall[:-1],
            precision[:-1] + recall[:-1],
            out=np.zeros_like(precision[:-1]),
            where=(precision[:-1] + recall[:-1]) > 0.0,
        )
        best_value = float(np.max(f1_values))
        candidate_indexes = np.flatnonzero(np.isclose(f1_values, best_value))
        best_index = min(
            candidate_indexes.tolist(),
            key=lambda index: (abs(float(thresholds[index]) - 0.5), float(thresholds[index])),
        )
        selected = float(thresholds[best_index])

    validation_metrics = evaluate_binary_predictions(
        target,
        scores,
        threshold=selected,
        split_name="validation split",
    )
    return ThresholdSelection(
        threshold=selected,
        objective=objective,
        objective_value=validation_metrics.f1,
        candidate_count=int(thresholds.size),
        validation_metrics=validation_metrics,
    )
