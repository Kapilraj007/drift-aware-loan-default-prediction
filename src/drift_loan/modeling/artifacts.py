"""Safe loading and feature-schema enforcement for persisted primary models."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .errors import ModelArtifactError, ModelingDataError
from .estimators import positive_class_probabilities
from .explanations import explain_transformed_features


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ModelArtifactError(
            "Artifact metadata points outside the requested model directory."
        ) from exc
    return resolved


def _feature_names(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    values = metadata.get("feature_names")
    if not isinstance(values, list) or not values or not all(
        isinstance(name, str) and name for name in values
    ):
        raise ModelArtifactError("metadata.json must contain a non-empty feature_names list.")
    names = tuple(values)
    if len(set(names)) != len(names):
        raise ModelArtifactError("metadata.json feature_names must be unique.")
    return names


def _feature_schema_sha256(feature_names: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(feature_names).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelBundle:
    """Primary model plus the exact feature/threshold contract needed by serving.

    This package deliberately accepts already-transformed feature matrices only.
    A caller that receives raw application input must run the shared Sprint 1
    transformer before using ``predict_proba_features``.
    """

    model: Any
    metadata: Mapping[str, Any]
    feature_names: tuple[str, ...]
    threshold: float
    model_version: str
    shap_explainer: Any | None = None

    def _prepared_features(self, features: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(features, pd.DataFrame):
            raise ModelingDataError("predict_proba_features requires a pandas DataFrame.")
        if not features.columns.is_unique:
            raise ModelingDataError("Feature DataFrame contains duplicate column names.")
        missing = [name for name in self.feature_names if name not in features.columns]
        if missing:
            raise ModelingDataError(
                f"Feature DataFrame is missing {len(missing)} required model features: {missing}"
            )
        extra = [name for name in features.columns if name not in self.feature_names]
        if extra:
            raise ModelingDataError(
                "Feature DataFrame contains columns outside the persisted feature schema: "
                f"{extra}"
            )
        prepared = features.loc[:, self.feature_names]
        try:
            numeric = prepared.astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise ModelingDataError("Feature DataFrame must contain numeric values.") from exc
        if numeric.empty:
            raise ModelingDataError("Feature DataFrame must contain at least one row.")
        if not np.isfinite(numeric.to_numpy()).all():
            raise ModelingDataError(
                "Feature DataFrame must not contain missing or non-finite values."
            )
        return numeric

    def predict_proba_features(self, features: pd.DataFrame) -> np.ndarray:
        """Score transformed feature rows in persisted training-schema order."""

        return positive_class_probabilities(self.model, self._prepared_features(features))

    def predict_features(self, features: pd.DataFrame) -> np.ndarray:
        """Return the persisted-threshold binary risk flag for transformed rows."""

        return (self.predict_proba_features(features) >= self.threshold).astype(np.int8)

    def explain_features(self, features: pd.DataFrame) -> np.ndarray:
        """Return signed class-1 SHAP attributions for transformed feature rows."""

        if self.shap_explainer is None:
            raise ModelArtifactError(
                "This model bundle does not include a persisted SHAP explainer."
            )
        return explain_transformed_features(self.shap_explainer, self._prepared_features(features))


def load_model_bundle(model_dir: Path | str) -> ModelBundle:
    """Load the versioned primary model and validate its schema and integrity hashes."""

    root = Path(model_dir).expanduser().resolve()
    if not root.is_dir():
        raise ModelArtifactError(f"Model artifact directory does not exist: {root}")
    metadata_path = root / "metadata.json"
    if not metadata_path.is_file():
        raise ModelArtifactError(f"Model metadata is missing: {metadata_path}")
    try:
        metadata_value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelArtifactError(f"Model metadata contains invalid JSON: {metadata_path}") from exc
    if not isinstance(metadata_value, dict):
        raise ModelArtifactError("Model metadata must contain a JSON object.")
    metadata: Mapping[str, Any] = MappingProxyType(metadata_value)
    feature_names = _feature_names(metadata)

    model_version = metadata.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise ModelArtifactError("Model metadata must contain a non-empty model_version.")
    threshold_value = metadata.get("threshold")
    if not isinstance(threshold_value, int | float) or isinstance(threshold_value, bool):
        raise ModelArtifactError("Model metadata must contain a numeric threshold.")
    threshold = float(threshold_value)
    if not np.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ModelArtifactError("Model metadata threshold must lie in [0, 1].")

    relative_artifact = metadata.get("model_artifact", "model.joblib")
    if not isinstance(relative_artifact, str) or not relative_artifact:
        raise ModelArtifactError("Model metadata model_artifact must be a non-empty relative path.")
    model_path = _inside(root, root / relative_artifact)
    if not model_path.is_file():
        raise ModelArtifactError(f"Primary model artifact is missing: {model_path}")
    expected_hash = metadata.get("model_artifact_sha256")
    if isinstance(expected_hash, str) and expected_hash:
        actual_hash = _sha256_file(model_path)
        if actual_hash != expected_hash:
            raise ModelArtifactError(
                "Primary model artifact SHA-256 does not match metadata; "
                "do not load a modified model."
            )

    schema_artifact = metadata.get("feature_schema_artifact")
    if isinstance(schema_artifact, str) and schema_artifact:
        schema_path = _inside(root, root / schema_artifact)
        if not schema_path.is_file():
            raise ModelArtifactError(f"Feature-schema artifact is missing: {schema_path}")
        try:
            schema_payload = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ModelArtifactError(
                f"Feature-schema artifact contains invalid JSON: {schema_path}"
            ) from exc
        if not isinstance(schema_payload, dict) or tuple(
            schema_payload.get("feature_names", ())
        ) != feature_names:
            raise ModelArtifactError(
                "Feature-schema artifact does not match metadata feature_names."
            )
        expected_schema_hash = metadata.get("feature_schema_sha256")
        actual_schema_hash = _feature_schema_sha256(feature_names)
        if expected_schema_hash != actual_schema_hash:
            raise ModelArtifactError(
                "Semantic feature-schema SHA-256 does not match model metadata."
            )
        if schema_payload.get("feature_schema_sha256") != actual_schema_hash:
            raise ModelArtifactError(
                "Feature-schema artifact does not match the semantic feature-schema digest."
            )
        expected_file_hash = metadata.get("feature_schema_file_sha256")
        if isinstance(expected_file_hash, str) and expected_file_hash:
            actual_file_hash = _sha256_file(schema_path)
            if actual_file_hash != expected_file_hash:
                raise ModelArtifactError(
                    "Feature-schema artifact SHA-256 does not match model metadata."
                )

    shap_explainer: Any | None = None
    shap_artifact = metadata.get("shap_explainer_artifact")
    if isinstance(shap_artifact, str) and shap_artifact:
        shap_path = _inside(root, root / shap_artifact)
        if not shap_path.is_file():
            raise ModelArtifactError(f"SHAP explainer artifact is missing: {shap_path}")
        expected_shap_hash = metadata.get("shap_explainer_sha256")
        if isinstance(expected_shap_hash, str) and expected_shap_hash:
            if _sha256_file(shap_path) != expected_shap_hash:
                raise ModelArtifactError("SHAP explainer SHA-256 does not match model metadata.")
        try:
            shap_explainer = joblib.load(shap_path)
        except (OSError, ValueError, TypeError, ImportError, ModuleNotFoundError) as exc:
            raise ModelArtifactError(
                f"Unable to load SHAP explainer artifact {shap_path}: {exc}"
            ) from exc

    try:
        model = joblib.load(model_path)
    except (OSError, ValueError, TypeError, ImportError, ModuleNotFoundError) as exc:
        raise ModelArtifactError(
            f"Unable to load primary model artifact {model_path}: {exc}"
        ) from exc
    if not hasattr(model, "predict_proba"):
        raise ModelArtifactError("Loaded primary model does not provide predict_proba().")
    return ModelBundle(
        model=model,
        metadata=metadata,
        feature_names=feature_names,
        threshold=threshold,
        model_version=model_version,
        shap_explainer=shap_explainer,
    )
