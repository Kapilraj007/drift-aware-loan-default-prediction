"""Database-free contracts for backend configuration and model serving."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest

import backend.app.services.inference_service as inference_module
import drift_loan.modeling as modeling_module
from backend.app.core.config import (
    Settings,
    database_target,
    direct_database_url_from_environment,
    mask_database_url,
    optional_environment_value,
    runtime_database_url_from_environment,
)
from backend.app.services.drift_service import DriftService
from backend.app.services.inference_service import (
    InferenceService,
    InputValidationError,
    LoadedModelArtifact,
    ModelArtifactError,
    _positive_probability,
    _read_json,
    _schema_hash,
)
from backend.app.services.shap_service import ShapService, _class_one_values
from drift_loan.data.exceptions import FeatureValidationError
from drift_loan.data.transform import LoanFeatureTransformer


class ProbabilityPredictor:
    """Pickle-safe test predictor for the joblib artifact contract."""

    def __init__(self, probability: float = 0.75) -> None:
        self.probability = probability
        self.calls: list[pd.DataFrame] = []

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        self.calls.append(features)
        return np.array([[1.0 - self.probability, self.probability]])


class PersistedDetector:
    """Small pickle-safe double for the persisted ADWIN compatibility path."""

    change_detected = True

    def __init__(self) -> None:
        self.values: list[float] = []

    def update(self, value: float) -> None:
        self.values.append(value)

class FeatureProbabilityPredictor(ProbabilityPredictor):
    def predict_proba_features(self, features: pd.DataFrame) -> np.ndarray:
        return self.predict_proba(features)


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@ep-test-pooler.example/db?sslmode=require",
        "direct_database_url": "postgresql+psycopg://u:p@ep-test.example/db?sslmode=require",
        "jwt_secret_key": "unit-test-key-with-at-least-32-characters",
        "model_artifact_directory": tmp_path / "model",
        "preprocessor_artifact_directory": tmp_path / "preprocessor",
    }
    values.update(overrides)
    return Settings(**values)


def _transformer(*names: str) -> LoanFeatureTransformer:
    transformer = LoanFeatureTransformer()
    transformer.feature_names_ = tuple(names)
    return transformer


def _artifact(
    predictor: object | None = None,
    *,
    feature_view: str = "unscaled",
    threshold: float = 0.5,
    metadata: dict[str, object] | None = None,
) -> LoadedModelArtifact:
    return LoadedModelArtifact(
        predictor=predictor or ProbabilityPredictor(),
        transformer=_transformer("annual_inc", "dti"),
        metadata=metadata or {},
        feature_view=feature_view,
        model_version="unit-v1",
        threshold=threshold,
    )


def test_settings_loads_dotenv_and_process_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "# local defaults",
                "DATABASE_URL='postgresql://u:p@ep-direct.example/db'",
                "DIRECT_DATABASE_URL=postgresql://u:p@ep-direct-pooler.example/db",
                'JWT_SECRET_KEY="dotenv-secret-that-is-longer-than-32-characters"',
                "CORS_ORIGINS=https://one.example, https://two.example,https://one.example",
                "ACCESS_TOKEN_MINUTES=17",
                "DB_MAX_OVERFLOW=0",
                "LOG_LEVEL=debug",
                "IGNORED LINE",
                "BAD-NAME=value",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PREDICTION_THRESHOLD", "0.61")

    with pytest.warns(UserWarning) as caught:
        settings = Settings.from_environment()

    assert len(caught) == 2
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.prediction_threshold == pytest.approx(0.61)
    assert settings.access_token_minutes == 17
    assert settings.db_max_overflow == 0
    assert settings.cors_origins == ("https://one.example", "https://two.example")
    assert settings.log_level == "DEBUG"
    assert optional_environment_value("BAD-NAME") is None


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("PREDICTION_THRESHOLD", "not-a-number", "must be a number"),
        ("PREDICTION_THRESHOLD", "1", "strictly between"),
        ("DB_POOL_SIZE", "many", "must be an integer"),
        ("DB_POOL_SIZE", "0", "at least 1"),
        ("DB_POOL_RECYCLE_SECONDS", "300", "below Neon's five-minute"),
        ("JWT_SECRET_KEY", "too-short", "at least 32"),
    ],
)
def test_settings_rejects_invalid_environment_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:p@ep-test-pooler.example/db?sslmode=require"
    )
    monkeypatch.setenv(
        "DIRECT_DATABASE_URL", "postgresql://u:p@ep-test.example/db?sslmode=require"
    )
    monkeypatch.setenv("JWT_SECRET_KEY", "unit-test-key-with-at-least-32-characters")
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=message):
        Settings.from_environment()


def test_database_url_helpers_mask_secrets_and_read_independent_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runtime = "postgres://owner:secret@ep-ci-pooler.example:5432/runtime?sslmode=require"
    direct = "postgresql://owner:secret@ep-ci.example/direct?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", runtime)
    monkeypatch.setenv("DIRECT_DATABASE_URL", direct)
    monkeypatch.setenv("OPTIONAL_SETTING", "  enabled  ")

    assert database_target(runtime) == ("ep-ci-pooler.example", "runtime")
    assert mask_database_url(runtime) == (
        "postgresql+psycopg://owner:***@ep-***.example:5432/runtime"
    )
    assert database_target(runtime_database_url_from_environment()) == (
        "ep-ci-pooler.example",
        "runtime",
    )
    assert database_target(direct_database_url_from_environment()) == (
        "ep-ci.example",
        "direct",
    )
    assert optional_environment_value("OPTIONAL_SETTING") == "enabled"
    assert optional_environment_value("MISSING_SETTING") is None


def test_settings_requires_database_urls_and_secure_constructor_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DIRECT_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Settings.from_environment()
    with pytest.raises(ValueError, match="at least 32"):
        _settings(tmp_path, jwt_secret_key="short")


def test_model_metadata_and_probability_formats_are_validated(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text('{"model_version": "v2"}', encoding="utf-8")
    assert _read_json(metadata_path) == {"model_version": "v2"}

    metadata_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="must be a JSON object"):
        _read_json(metadata_path)
    metadata_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="Invalid model metadata"):
        _read_json(metadata_path)
    with pytest.raises(ModelArtifactError, match="Invalid model metadata"):
        _read_json(tmp_path / "missing.json")

    assert _positive_probability([[0.2, 0.8]]) == pytest.approx(0.8)
    assert _positive_probability([0.35]) == pytest.approx(0.35)
    for invalid in ([[0.2]], [[0.1, 0.9], [0.8, 0.2]], [0.2, 0.8], [[[0.2, 0.8]]]):
        with pytest.raises(ModelArtifactError, match="unsupported shape"):
            _positive_probability(invalid)
    for invalid in ([np.nan], [1.01], [-0.01]):
        with pytest.raises(ModelArtifactError, match="invalid probability"):
            _positive_probability(invalid)


def test_artifact_schema_threshold_and_view_are_validated(tmp_path: Path) -> None:
    service = InferenceService(_settings(tmp_path))
    valid = _artifact(
        metadata={
            "feature_names": ["annual_inc", "dti"],
            "feature_schema_sha256": _schema_hash(["annual_inc", "dti"]),
        }
    )
    service._validate_artifact(valid)

    invalid_artifacts = [
        (_artifact(feature_view="raw"), "feature_view"),
        (_artifact(threshold=1.0), "threshold"),
        (_artifact(metadata={"feature_names": ["wrong"]}), "feature names"),
        (_artifact(metadata={"feature_schema_sha256": "wrong"}), "schema hashes"),
    ]
    for artifact, message in invalid_artifacts:
        with pytest.raises(ModelArtifactError, match=message):
            service._validate_artifact(artifact)


def test_joblib_fallback_loads_metadata_and_caches_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    settings.model_artifact_directory.mkdir()
    joblib.dump(
        {
            "estimator": ProbabilityPredictor(0.64),
            "metadata": {"model_version": "embedded", "feature_view": "scaled"},
        },
        settings.model_artifact_directory / "classifier.joblib",
    )
    (settings.model_artifact_directory / "metadata.json").write_text(
        json.dumps(
            {
                "model_version": "sidecar",
                "prediction_threshold": 0.6,
                "feature_names": ["annual_inc", "dti"],
            }
        ),
        encoding="utf-8",
    )
    transformer = _transformer("annual_inc", "dti")
    monkeypatch.setattr(inference_module, "load_transformer", lambda _: transformer)
    service = InferenceService(settings)
    monkeypatch.setattr(service, "_load_from_modeling_package", lambda: None)

    description = service.describe()
    assert description["model_version"] == "sidecar"
    assert description["feature_view"] == "scaled"
    assert description["prediction_threshold"] == pytest.approx(0.6)
    assert description["feature_count"] == 2
    assert description["feature_schema_sha256"] == _schema_hash(["annual_inc", "dti"])
    assert service._ensure_artifact() is service._ensure_artifact()
    service.clear_cache()
    assert service._artifact is None


def test_joblib_fallback_reports_missing_and_incompatible_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    settings.model_artifact_directory.mkdir()
    service = InferenceService(settings)
    with pytest.raises(ModelArtifactError, match="No model artifact"):
        service._load_joblib_fallback()

    artifact_path = settings.model_artifact_directory / "model.joblib"
    artifact_path.write_text("not a joblib file", encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="Could not load model artifact"):
        service._load_joblib_fallback()

    joblib.dump({"metadata": {}}, artifact_path)
    with pytest.raises(ModelArtifactError, match="does not expose"):
        service._load_joblib_fallback()

    joblib.dump(ProbabilityPredictor(), artifact_path)
    monkeypatch.setattr(
        inference_module,
        "load_transformer",
        lambda _: (_ for _ in ()).throw(ValueError("incompatible transformer")),
    )
    with pytest.raises(ModelArtifactError, match="Could not load shared preprocessing"):
        service._load_joblib_fallback()


def test_prediction_uses_selected_feature_view_and_maps_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transformed = SimpleNamespace(
        features=pd.DataFrame({"annual_inc": [50_000.0], "dti": [22.0]}),
        scaled_features=pd.DataFrame({"annual_inc": [0.4], "dti": [-0.2]}),
    )
    monkeypatch.setattr(
        inference_module, "transform_features", lambda *_args, **_kwargs: transformed
    )
    predictor = FeatureProbabilityPredictor(0.75)
    service = InferenceService(_settings(tmp_path))
    service._artifact = _artifact(predictor, feature_view="scaled", threshold=0.7)

    result = service.predict({"annual_inc": 50_000, "dti": 22})

    assert result.score == pytest.approx(0.75)
    assert result.risk_flag is True
    assert result.model_features.equals(transformed.scaled_features)
    assert predictor.calls[0].equals(transformed.scaled_features)
    assert result.raw_features == {"annual_inc": 50_000, "dti": 22}
    with pytest.raises(TypeError, match="dictionary"):
        service.predict([])  # type: ignore[arg-type]

    def invalid_features(*_args: object, **_kwargs: object) -> object:
        raise FeatureValidationError("Invalid value for 'annual_inc'")

    monkeypatch.setattr(inference_module, "transform_features", invalid_features)
    with pytest.raises(InputValidationError) as caught:
        service.predict({"annual_inc": "bad"})
    assert caught.value.detail == [
        {"field": "annual_inc", "message": "Invalid value for 'annual_inc'"}
    ]

    monkeypatch.setattr(
        inference_module,
        "transform_features",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )
    with pytest.raises(ModelArtifactError, match="feature transformation failed"):
        service.predict({"annual_inc": 1})


def test_prediction_wraps_predictor_failures(tmp_path: Path) -> None:
    service = InferenceService(_settings(tmp_path))
    features = pd.DataFrame({"annual_inc": [1.0], "dti": [2.0]})

    class RaisingPredictor:
        def predict_proba(self, _: pd.DataFrame) -> object:
            raise RuntimeError("scoring unavailable")

    with pytest.raises(ModelArtifactError, match="Model scoring failed"):
        service._predict(_artifact(RaisingPredictor()), features)


def test_shap_service_normalizes_formats_and_degrades_explicitly() -> None:
    one_dimensional = np.array([0.2, -0.1])
    np.testing.assert_allclose(_class_one_values(one_dimensional), one_dimensional)
    np.testing.assert_allclose(
        _class_one_values(np.array([[0.2, -0.1]])), one_dimensional
    )
    np.testing.assert_allclose(
        _class_one_values([np.zeros((1, 2)), [[0.2, -0.1]]]), one_dimensional
    )
    np.testing.assert_allclose(
        _class_one_values(np.array([[[0.0, 0.2], [0.0, -0.1]]])), one_dimensional
    )
    with pytest.raises(ValueError, match="positive class"):
        _class_one_values([np.zeros((1, 2))])
    with pytest.raises(ValueError, match="Unsupported SHAP"):
        _class_one_values(np.zeros((1, 1, 1, 1)))

    features = pd.DataFrame({"annual_inc": [np.float64(50_000)], "custom_value": [object()]})
    artifact = SimpleNamespace(
        predictor=SimpleNamespace(shap_values=lambda _: np.array([[-0.4, 0.2]]))
    )
    result = SimpleNamespace(artifact=artifact, model_features=features)
    explanation = ShapService().explain(result, top_k=2)
    assert explanation.available is True
    assert explanation.narrative == "Elevated risk is driven primarily by custom value."
    assert explanation.top_features[0].display_name == "annual income"
    assert explanation.top_features[0].direction == "risk_reducing"
    assert explanation.top_features[1].feature_value is None
    assert explanation.to_dict()["top_features"][0]["feature"] == "annual_inc"

    mismatched = SimpleNamespace(
        artifact=SimpleNamespace(predictor=SimpleNamespace(shap_values=lambda _: np.array([0.2]))),
        model_features=features,
    )
    assert ShapService().explain(mismatched).narrative.endswith("schema is incompatible.")
    broken = SimpleNamespace(
        artifact=SimpleNamespace(
            predictor=SimpleNamespace(
                shap_values=lambda _: (_ for _ in ()).throw(ValueError("bad explainer"))
            )
        ),
        model_features=features,
    )
    assert ShapService().explain(broken).narrative.endswith("could not be generated for it.")


def test_modeling_bundle_loader_honors_bundle_metadata_and_maps_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transformer = _transformer("annual_inc", "dti")
    bundle = ProbabilityPredictor()
    bundle.transformer = transformer  # type: ignore[attr-defined]
    bundle.metadata = {  # type: ignore[attr-defined]
        "feature_view": "scaled",
        "model_version": "bundle-v3",
        "prediction_threshold": 0.42,
    }
    monkeypatch.setattr(modeling_module, "load_model_bundle", lambda _: bundle)
    service = InferenceService(_settings(tmp_path))

    artifact = service._load_from_modeling_package()

    assert artifact is not None
    assert artifact.predictor is bundle
    assert artifact.transformer is transformer
    assert artifact.feature_view == "scaled"
    assert artifact.model_version == "bundle-v3"
    assert artifact.threshold == pytest.approx(0.42)

    monkeypatch.setattr(
        modeling_module,
        "load_model_bundle",
        lambda _: (_ for _ in ()).throw(FileNotFoundError()),
    )
    assert service._load_from_modeling_package() is None
    monkeypatch.setattr(
        modeling_module,
        "load_model_bundle",
        lambda _: (_ for _ in ()).throw(RuntimeError("corrupt bundle")),
    )
    with pytest.raises(ModelArtifactError, match="Could not load drift_loan.modeling bundle"):
        service._load_from_modeling_package()


def test_modeling_bundle_loader_requires_shared_transformer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = ProbabilityPredictor()
    monkeypatch.setattr(modeling_module, "load_model_bundle", lambda _: bundle)
    monkeypatch.setattr(inference_module, "load_transformer", lambda _: object())

    with pytest.raises(ModelArtifactError, match="LoanFeatureTransformer"):
        InferenceService(_settings(tmp_path))._load_from_modeling_package()

def test_drift_service_loads_persisted_detector_and_validates_scores(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.model_artifact_directory.mkdir()
    joblib.dump(
        PersistedDetector(),
        settings.model_artifact_directory / "adwin_detector.joblib",
    )
    service = DriftService(settings)

    assert service.snapshot().status == "not_observed"
    observed = service.observe_score(np.float64(0.65))

    assert observed.status == "drift_detected"
    assert observed.score_stream_count == 1
    assert observed.latest_score == pytest.approx(0.65)
    assert service._load_detector() is service._detector
    assert service._detector.values == [0.65]
    assert observed.to_dict()["adwin_change_detected"] is True
    for invalid in (np.nan, -0.01, 1.01):
        with pytest.raises(ValueError, match="finite probability"):
            service.observe_score(invalid)


def test_drift_rehydrate_tolerates_partial_legacy_snapshot(tmp_path: Path) -> None:
    service = DriftService(_settings(tmp_path))
    updated_at = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)

    snapshot = service.rehydrate(
        [],
        {
            "score_stream_count": 7,
            "latest_score": 0.25,
            "adwin_change_detected": True,
            "updated_at": updated_at,
            "feature_results": [None, {"feature": "missing-fields"}],
        },
    )

    assert snapshot.status == "drift_detected"
    assert snapshot.score_stream_count == 7
    assert snapshot.latest_score == pytest.approx(0.25)
    assert snapshot.updated_at == updated_at
    assert snapshot.feature_results == ()

    snapshot = service.rehydrate([], {"updated_at": "not-an-iso-timestamp"})
    assert snapshot.updated_at is None


def test_drift_numeric_column_selection_and_input_guards(tmp_path: Path) -> None:
    service = DriftService(_settings(tmp_path))
    reference = pd.DataFrame(
        {
            "income": ["100", "200", "bad"],
            "target": [0, 1, 0],
            "sparse": [1, None, None],
            "reference_only": [1, 2, 3],
        }
    )
    current = pd.DataFrame(
        {
            "income": [110, 220, None],
            "target": [0, 1, 0],
            "sparse": [None, 2, None],
        }
    )

    assert service._common_numeric_columns(reference, current) == ["income"]
    with pytest.raises(ValueError, match="alpha"):
        service.evaluate_feature_drift(reference, current, alpha=1.0)
    with pytest.raises(ValueError, match="must contain rows"):
        service.evaluate_feature_drift(reference.iloc[0:0], current)