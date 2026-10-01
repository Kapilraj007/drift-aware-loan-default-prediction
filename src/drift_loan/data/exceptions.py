"""Domain-specific exceptions for the Sprint 1 data pipeline."""

from __future__ import annotations


class DataPipelineError(RuntimeError):
    """Base class for recoverable data-pipeline failures."""


class SchemaValidationError(DataPipelineError, ValueError):
    """Raised when an input does not satisfy the LendingClub schema contract."""


class FeatureValidationError(DataPipelineError, ValueError):
    """Raised when a feature value cannot be parsed or safely transformed."""


class ArtifactError(DataPipelineError):
    """Raised when fitted preprocessing artifacts are missing or incompatible."""


class FeatureStoreError(DataPipelineError):
    """Raised when a feature store cannot be written or read safely."""
