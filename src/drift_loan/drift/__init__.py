"""Public API for feature-store time slicing and synthetic drift simulation."""

from .harness import (
    DEFAULT_METADATA_COLUMNS,
    FeatureStoreSlice,
    apply_perturbations,
    load_feature_window,
    run_drift_simulation,
    slice_feature_store,
)
from .models import (
    NumericSummary,
    PerturbationReport,
    PerturbationSpec,
    ShiftMode,
    SimulationManifest,
    SimulationResult,
    TimeWindow,
)

__all__ = [
    "DEFAULT_METADATA_COLUMNS",
    "FeatureStoreSlice",
    "NumericSummary",
    "PerturbationReport",
    "PerturbationSpec",
    "ShiftMode",
    "SimulationManifest",
    "SimulationResult",
    "TimeWindow",
    "apply_perturbations",
    "load_feature_window",
    "run_drift_simulation",
    "slice_feature_store",
]
