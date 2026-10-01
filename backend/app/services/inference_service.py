"""Lazy, schema-checked model loading and single-application scoring."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import joblib
import numpy as np
import pandas as pd

from drift_loan.data.transform import LoanFeatureTransformer, load_transformer, transform_features

from ..core.config import Settings


class ModelArtifactError(RuntimeError):
    """Raised when a model artifact is absent, incompatible, or cannot score."""


class _FeaturePredictor(Protocol):
    def predict_proba(self, values: pd.DataFrame) -> Any: ...


@dataclass(frozen=True, slots=True)
class LoadedModelArtifact:
    """The cached model, canonical transformer, and validated metadata."""

    predictor: Any
    transformer: LoanFeatureTransformer
    metadata: dict[str, Any]
    feature_view: str
    model_version: str
    threshold: float


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """A score plus the exact model matrix used to produce it."""

    score: float
    risk_flag: bool
    threshold: float
    model_version: str
    artifact: LoadedModelArtifact
    raw_features: dict[str, object]
    model_features: pd.DataFrame


def _schema_hash(columns: list[str]) -> str:
    return hashlib.sha256("\n".join(columns).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        contents = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelArtifactError(f"Invalid model metadata at {path}: {exc}") from exc
    if not isinstance(contents, dict):
        raise ModelArtifactError(f"Model metadata at {path} must be a JSON object")
    return contents


def _positive_probability(predictions: Any) -> float:
    values = np.asarray(predictions, dtype="float64")
    if values.ndim == 2:
        if values.shape[0] != 1 or values.shape[1] < 2:
            raise ModelArtifactError(
                "Model predict_proba returned unsupported shape "
                f"{tuple(values.shape)}; expected (1, 2)"
            )
        score = float(values[0, 1])
    elif values.ndim == 1 and values.shape == (1,):
        score = float(values[0])
    else:
        raise ModelArtifactError(
            f"Model predict_proba returned unsupported shape {tuple(values.shape)}"
        )
    if not np.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ModelArtifactError(f"Model returned an invalid probability: {score!r}")
    return score


class InferenceService:
    """Loads the Sprint 2 model only when the first prediction is requested.

    The public contract intentionally favours an optional
    ``drift_loan.modeling.load_model_bundle`` implementation.  A lightweight
    joblib fallback keeps the API compatible with a conventional
    ``model.joblib`` + JSON metadata artifact and makes artifact failures
    deterministic rather than import-time failures.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._artifact: LoadedModelArtifact | None = None

    def _load_from_modeling_package(self) -> LoadedModelArtifact | None:
        """Use the modelling package when its documented bundle API is present."""

        try:
            from drift_loan.modeling import load_model_bundle  # type: ignore[attr-defined]
        except ImportError:
            return None

        try:
            bundle = load_model_bundle(self.settings.model_artifact_directory)
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise ModelArtifactError(f"Could not load drift_loan.modeling bundle: {exc}") from exc

        predictor = bundle
        metadata = dict(getattr(bundle, "metadata", {}) or {})
        transformer = getattr(bundle, "transformer", None)
        if transformer is None:
            transformer = load_transformer(self.settings.preprocessor_artifact_directory)
        if not isinstance(transformer, LoanFeatureTransformer):
            raise ModelArtifactError("Model bundle did not provide a LoanFeatureTransformer")
        feature_view = str(
            metadata.get("feature_view", getattr(bundle, "feature_view", "unscaled"))
        )
        model_version = str(
            metadata.get("model_version", getattr(bundle, "model_version", "unknown"))
        )
        threshold = float(metadata.get("prediction_threshold", self.settings.prediction_threshold))
        return LoadedModelArtifact(
            predictor=predictor,
            transformer=transformer,
            metadata=metadata,
            feature_view=feature_view,
            model_version=model_version,
            threshold=threshold,
        )

    def _load_joblib_fallback(self) -> LoadedModelArtifact:
        model_directory = self.settings.model_artifact_directory
        candidates = (
            model_directory / "model.joblib",
            model_directory / "model.pkl",
            model_directory / "classifier.joblib",
        )
        model_path = next((path for path in candidates if path.is_file()), None)
        if model_path is None:
            choices = ", ".join(str(path) for path in candidates)
            raise ModelArtifactError(
                "No model artifact is available. Expected one of: " + choices
            )
        metadata_candidates = (
            model_directory / "model_metadata.json",
            model_directory / "metadata.json",
        )
        metadata_path = next((path for path in metadata_candidates if path.is_file()), None)
        metadata = _read_json(metadata_path) if metadata_path is not None else {}
        try:
            loaded = joblib.load(model_path)
        except Exception as exc:
            raise ModelArtifactError(f"Could not load model artifact {model_path}: {exc}") from exc

        # The training layer may persist either the estimator itself or a
        # compact mapping that includes an estimator and training metadata.
        predictor = loaded
        if isinstance(loaded, dict):
            predictor = loaded.get("model", loaded.get("estimator"))
            embedded_metadata = loaded.get("metadata")
            if isinstance(embedded_metadata, dict):
                metadata = {**embedded_metadata, **metadata}
        if predictor is None or not hasattr(predictor, "predict_proba"):
            raise ModelArtifactError(
                f"Model artifact {model_path} does not expose a predict_proba method"
            )

        try:
            transformer = load_transformer(self.settings.preprocessor_artifact_directory)
        except Exception as exc:
            raise ModelArtifactError(
                f"Could not load shared preprocessing artifact: {exc}"
            ) from exc
        feature_view = str(metadata.get("feature_view", "unscaled"))
        model_version = str(metadata.get("model_version", model_path.stem))
        threshold = float(metadata.get("prediction_threshold", self.settings.prediction_threshold))
        return LoadedModelArtifact(
            predictor=predictor,
            transformer=transformer,
            metadata=metadata,
            feature_view=feature_view,
            model_version=model_version,
            threshold=threshold,
        )

    def _ensure_artifact(self) -> LoadedModelArtifact:
        if self._artifact is None:
            artifact = self._load_from_modeling_package()
            self._artifact = artifact if artifact is not None else self._load_joblib_fallback()
            self._validate_artifact(self._artifact)
        return self._artifact

    @staticmethod
    def _validate_artifact(artifact: LoadedModelArtifact) -> None:
        if artifact.feature_view not in {"unscaled", "scaled"}:
            raise ModelArtifactError(
                "Model metadata feature_view must be either 'unscaled' or 'scaled'"
            )
        if not 0.0 < artifact.threshold < 1.0:
            raise ModelArtifactError("Model prediction threshold must be strictly between 0 and 1")
        expected_names = artifact.metadata.get("feature_names")
        actual_names = list(artifact.transformer.feature_names_)
        if expected_names is not None and list(expected_names) != actual_names:
            raise ModelArtifactError("Model and transformer feature names do not match")
        expected_hash = artifact.metadata.get("feature_schema_sha256")
        actual_hash = _schema_hash(actual_names)
        if expected_hash is not None and str(expected_hash) != actual_hash:
            raise ModelArtifactError("Model and transformer feature schema hashes do not match")

    @staticmethod
    def _predict(artifact: LoadedModelArtifact, features: pd.DataFrame) -> float:
        predictor = artifact.predictor
        try:
            if hasattr(predictor, "predict_proba_features"):
                probabilities = predictor.predict_proba_features(features)
            else:
                probabilities = predictor.predict_proba(features)
        except Exception as exc:
            raise ModelArtifactError(f"Model scoring failed: {exc}") from exc
        return _positive_probability(probabilities)

    def predict(self, raw_features: dict[str, object]) -> InferenceResult:
        """Transform one raw application and return its default-risk score."""

        if not isinstance(raw_features, dict):
            raise TypeError("raw_features must be a dictionary")
        artifact = self._ensure_artifact()
        try:
            transformed = transform_features(
                pd.DataFrame([raw_features]),
                transformer=artifact.transformer,
                include_target=False,
            )
        except Exception as exc:
            raise ModelArtifactError(f"Application feature transformation failed: {exc}") from exc
        features = (
            transformed.scaled_features
            if artifact.feature_view == "scaled"
            else transformed.features
        )
        score = self._predict(artifact, features)
        return InferenceResult(
            score=score,
            risk_flag=score >= artifact.threshold,
            threshold=artifact.threshold,
            model_version=artifact.model_version,
            artifact=artifact,
            raw_features=dict(raw_features),
            model_features=features,
        )

    def describe(self) -> dict[str, object]:
        """Return validated artifact metadata without scoring an application."""

        artifact = self._ensure_artifact()
        return {
            "model_version": artifact.model_version,
            "feature_view": artifact.feature_view,
            "prediction_threshold": artifact.threshold,
            "feature_count": len(artifact.transformer.feature_names_),
            "feature_schema_sha256": _schema_hash(list(artifact.transformer.feature_names_)),
            "metadata": dict(artifact.metadata),
        }

    def clear_cache(self) -> None:
        """Clear the lazy cache; intended for explicit admin reload flows/tests."""

        self._artifact = None
