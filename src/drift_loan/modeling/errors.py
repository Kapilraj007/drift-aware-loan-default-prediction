"""Domain-specific errors for Sprint 2 model development."""

from __future__ import annotations


class ModelingError(Exception):
    """Base class for expected model-development failures."""


class ModelingDataError(ModelingError):
    """Raised when a feature-store input violates the modeling contract."""


class ModelingDependencyError(ModelingError):
    """Raised when an optional model-family dependency is unavailable."""


class ModelArtifactError(ModelingError):
    """Raised when a persisted model bundle is missing, corrupt, or incompatible."""
