"""Sprint 2 temporal model-training and model-serving artifact APIs."""

from .artifacts import ModelBundle, load_model_bundle
from .data import (
    METADATA_COLUMNS,
    REQUIRED_SPLITS,
    ModelingDataset,
    load_modeling_dataset,
)
from .errors import (
    ModelArtifactError,
    ModelingDataError,
    ModelingDependencyError,
    ModelingError,
)
from .estimators import (
    MODEL_NAMES,
    EstimatorFactory,
    create_estimator,
    positive_class_probabilities,
)
from .explanations import create_tree_explainer, explain_transformed_features
from .metrics import (
    ClassificationMetrics,
    ThresholdSelection,
    evaluate_binary_predictions,
    select_validation_threshold,
)
from .monitoring import calibrate_adwin_detector
from .training import (
    CandidateEvaluation,
    CrossValidationResult,
    FoldEvaluation,
    ModelEvaluation,
    ModelTrainingResult,
    TemporalFold,
    TrainingConfig,
    cross_validate_model_candidates,
    expanding_window_folds,
    train_sprint2_models,
)

__all__ = [
    "METADATA_COLUMNS",
    "MODEL_NAMES",
    "REQUIRED_SPLITS",
    "CandidateEvaluation",
    "ClassificationMetrics",
    "CrossValidationResult",
    "EstimatorFactory",
    "FoldEvaluation",
    "ModelArtifactError",
    "ModelBundle",
    "ModelEvaluation",
    "ModelTrainingResult",
    "ModelingDataError",
    "ModelingDataset",
    "ModelingDependencyError",
    "ModelingError",
    "TemporalFold",
    "ThresholdSelection",
    "TrainingConfig",
    "calibrate_adwin_detector",
    "create_estimator",
    "create_tree_explainer",
    "cross_validate_model_candidates",
    "evaluate_binary_predictions",
    "expanding_window_folds",
    "explain_transformed_features",
    "load_model_bundle",
    "load_modeling_dataset",
    "positive_class_probabilities",
    "select_validation_threshold",
    "train_sprint2_models",
]
