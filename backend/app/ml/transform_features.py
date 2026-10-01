"""FastAPI-facing re-export of the canonical train/serve feature transform.

No preprocessing logic belongs in the API package.  Importing from this module
keeps service code ergonomic while guaranteeing it executes the exact artifact
and implementation used by the training pipeline.
"""

from drift_loan.data.transform import (
    LoanFeatureTransformer,
    TransformedFeatures,
    load_transformer,
    transform_features,
)

__all__ = [
    "LoanFeatureTransformer",
    "TransformedFeatures",
    "load_transformer",
    "transform_features",
]
