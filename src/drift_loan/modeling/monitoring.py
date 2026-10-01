"""Model-score monitoring state initialized during Sprint 2 training."""

from __future__ import annotations

import importlib

import numpy as np

from .errors import ModelingDataError, ModelingDependencyError


def calibrate_adwin_detector(
    validation_scores: object,
    *,
    delta: float = 0.002,
) -> object:
    """Initialize ADWIN from chronological validation prediction scores.

    The held-out shift split is deliberately excluded from this calibration so
    its evaluation remains untouched. Future monitoring services can load this
    state and update it one score at a time as applications arrive.
    """

    if not isinstance(delta, float | int | np.floating | np.integer):
        raise ModelingDataError("ADWIN delta must be a finite number in (0, 1).")
    resolved_delta = float(delta)
    if not np.isfinite(resolved_delta) or not 0.0 < resolved_delta < 1.0:
        raise ModelingDataError("ADWIN delta must be a finite number in (0, 1).")
    try:
        scores = np.asarray(validation_scores, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise ModelingDataError("ADWIN calibration scores must be numeric.") from exc
    if scores.size == 0 or not np.isfinite(scores).all():
        raise ModelingDataError("ADWIN calibration scores must be non-empty and finite.")
    if np.any(scores < 0.0) or np.any(scores > 1.0):
        raise ModelingDataError("ADWIN calibration scores must be probabilities in [0, 1].")

    try:
        river_drift = importlib.import_module("river.drift")
    except ImportError as exc:
        raise ModelingDependencyError(
            "river is required to initialize the Sprint 2 ADWIN detector state."
        ) from exc
    detector = river_drift.ADWIN(delta=resolved_delta)
    for score in scores:
        detector.update(float(score))
    return detector
