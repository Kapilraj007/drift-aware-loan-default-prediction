"""API-level tests for Sprint 2 auth, persistence, scoring, and audit flows."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.services.drift_service import DriftService
from backend.app.services.shap_service import Explanation, FeatureAttribution, ShapService


def _features() -> dict[str, object]:
    return {
        "annual_inc": 75_000.0,
        "dti": 16.5,
        "revol_util": "38%",
        "revol_bal": 8_200.0,
        "open_acc": 10.0,
        "total_acc": 25.0,
        "delinq_2yrs": 0.0,
        "inq_last_6mths": 1.0,
        "loan_amnt": 12_000.0,
        "term": "36 months",
        "int_rate": "11.2%",
        "installment": 394.0,
        "grade": "B",
        "sub_grade": "B3",
        "purpose": "debt_consolidation",
        "emp_length": "5 years",
        "home_ownership": "RENT",
        "earliest_cr_line": "Jan-2004",
        "issue_d": "Jan-2018",
    }


class _FakeInferenceService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def predict(self, raw_features: dict[str, object]) -> SimpleNamespace:
        self.calls.append(raw_features)
        return SimpleNamespace(
            score=0.72,
            risk_flag=True,
            threshold=0.50,
            model_version="test-model-v1",
        )

    def describe(self) -> dict[str, object]:
        return {
            "model_version": "test-model-v1",
            "feature_view": "unscaled",
            "prediction_threshold": 0.50,
            "feature_count": 53,
            "feature_schema_sha256": "test-schema",
            "metadata": {"training_run": {"id": "run-1", "status": "completed"}},
        }


class _FakeShapService:
    def explain(self, result: object) -> Explanation:
        del result
        return Explanation(
            available=True,
            narrative="Elevated risk is driven primarily by debt-to-income ratio.",
            top_features=(
                FeatureAttribution(
                    feature="dti",
                    display_name="debt-to-income ratio",
                    contribution=0.31,
                    direction="risk_increasing",
                    feature_value=16.5,
                ),
            ),
        )


class _PersistedExplainer:
    """Small TreeExplainer-shaped test double for the serialized-artifact path."""

    def shap_values(
        self,
        features: pd.DataFrame,
        *,
        check_additivity: bool = False,
    ) -> list[np.ndarray]:
        del check_additivity
        zero_values = np.zeros((len(features), len(features.columns)))
        positive_values = np.tile(
            np.array([0.20, -0.35, 0.10]),
            (len(features), 1),
        )
        return [zero_values, positive_values]


def _client(*, cors_origins: tuple[str, ...] = ()) -> tuple[TestClient, _FakeInferenceService]:
    settings = Settings(
        database_url="sqlite://",
        jwt_secret_key="test-secret",
        model_artifact_directory="unused-model-directory",  # type: ignore[arg-type]
        preprocessor_artifact_directory="unused-preprocessor-directory",  # type: ignore[arg-type]
        cors_origins=cors_origins,
    )
    app = create_app(settings)
    inference = _FakeInferenceService()
    app.state.inference_service = inference
    app.state.shap_service = _FakeShapService()
    app.state.drift_service = DriftService(settings)
    return TestClient(app), inference


def _token(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_backend_full_auditable_prediction_flow() -> None:
    client, inference = _client()
    with client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json()["status"] == "ready"

        # The first account is deliberately converted to an admin bootstrap.
        bootstrap = client.post(
            "/api/v1/auth/register",
            json={"username": "admin", "password": "a-secure-password", "role": "loan_officer"},
        )
        assert bootstrap.status_code == 201, bootstrap.text
        assert bootstrap.json()["role"] == "admin"
        admin_token = _token(client, "admin", "a-secure-password")

        officer = client.post(
            "/api/v1/auth/register",
            headers=_headers(admin_token),
            json={
                "username": "officer",
                "password": "another-secure-password",
                "role": "loan_officer",
            },
        )
        assert officer.status_code == 201, officer.text
        officer_token = _token(client, "officer", "another-secure-password")

        created = client.post(
            "/api/v1/applications",
            headers=_headers(officer_token),
            json={"external_reference": "case-42", "features": _features()},
        )
        assert created.status_code == 201, created.text
        application_id = created.json()["id"]

        prediction = client.post(
            "/api/v1/predictions",
            headers=_headers(officer_token),
            json={"application_id": application_id},
        )
        assert prediction.status_code == 201, prediction.text
        body = prediction.json()
        assert body["application_id"] == application_id
        assert body["score"] == 0.72
        assert body["risk_flag"] is True
        assert body["explanation"]["available"] is True
        assert body["detector_state"]["score_stream_count"] == 1
        assert inference.calls == [_features()]

        feedback = client.post(
            "/api/v1/feedback",
            headers=_headers(officer_token),
            json={
                "prediction_id": body["id"],
                "decision": "escalate",
                "agreed_with_model": True,
                "note": "Needs manual income verification.",
            },
        )
        assert feedback.status_code == 201, feedback.text
        assert feedback.json()["detector_state"]["score_stream_count"] == 1

        officer_monitor = client.get(
            "/api/v1/monitoring/status", headers=_headers(officer_token)
        )
        assert officer_monitor.status_code == 403
        monitor = client.get("/api/v1/monitoring/status", headers=_headers(admin_token))
        assert monitor.status_code == 200, monitor.text
        assert monitor.json()["score_stream_count"] == 1

        model = client.get("/api/v1/model", headers=_headers(admin_token))
        assert model.status_code == 200, model.text
        assert model.json()["model_version"] == "test-model-v1"
        runs = client.get("/api/v1/training-runs", headers=_headers(admin_token))
        assert runs.status_code == 200, runs.text
        assert runs.json()["runs"] == [{"id": "run-1", "status": "completed"}]


def test_prediction_request_requires_one_input_source_and_monitoring_runs_ks() -> None:
    client, _ = _client()
    with client:
        client.post(
            "/api/v1/auth/register",
            json={"username": "admin", "password": "a-secure-password", "role": "admin"},
        )
        token = _token(client, "admin", "a-secure-password")
        invalid = client.post("/api/v1/predictions", headers=_headers(token), json={})
        assert invalid.status_code == 422

        direct = client.post(
            "/api/v1/predictions",
            headers=_headers(token),
            json={"features": _features()},
        )
        assert direct.status_code == 201, direct.text
        assert direct.json()["application_id"] is None

        drift = client.post(
            "/api/v1/monitoring/feature-drift",
            headers=_headers(token),
            json={
                "reference_rows": [{"dti": 1.0}, {"dti": 1.1}, {"dti": 0.9}],
                "current_rows": [{"dti": 10.0}, {"dti": 11.0}, {"dti": 12.0}],
                "alpha": 0.5,
            },
        )
        assert drift.status_code == 200, drift.text
        assert drift.json()["evaluated_features"] == 1


def test_shap_service_prefers_a_persisted_bundle_explainer() -> None:
    features = pd.DataFrame(
        {"dti": [16.5], "int_rate": [11.2], "grade": [1.0]}
    )
    result = SimpleNamespace(
        artifact=SimpleNamespace(
            predictor=SimpleNamespace(shap_explainer=_PersistedExplainer())
        ),
        model_features=features,
    )

    explanation = ShapService().explain(result)

    assert explanation.available is True
    assert explanation.top_features[0].feature == "int_rate"
    assert explanation.top_features[0].direction == "risk_reducing"


def test_cors_allows_the_configured_frontend_origin() -> None:
    client, _ = _client(cors_origins=("http://frontend.example",))
    with client:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://frontend.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://frontend.example"


def test_officer_prediction_creates_assignment_without_a_frontend_preflight() -> None:
    """A direct score cannot bypass the durable score-only study arm."""

    client, _ = _client()
    with client:
        bootstrap = client.post(
            "/api/v1/auth/register",
            json={"username": "admin", "password": "a-secure-password", "role": "admin"},
        )
        assert bootstrap.status_code == 201, bootstrap.text
        admin_token = _token(client, "admin", "a-secure-password")

        officer = client.post(
            "/api/v1/auth/register",
            headers=_headers(admin_token),
            json={
                "username": "officer",
                "password": "another-secure-password",
                "role": "loan_officer",
            },
        )
        assert officer.status_code == 201, officer.text
        officer_token = _token(client, "officer", "another-secure-password")

        prediction = client.post(
            "/api/v1/predictions",
            headers=_headers(officer_token),
            json={"features": _features()},
        )
        assert prediction.status_code == 201, prediction.text
        prediction_body = prediction.json()
        assert prediction_body["study_variant"] in {"score_only", "explanation_shown"}

        assignment = client.get(
            "/api/v1/experiments/explanation-assignment",
            headers=_headers(officer_token),
        )
        assert assignment.status_code == 200, assignment.text
        assert assignment.json()["variant"] == prediction_body["study_variant"]
        if prediction_body["study_variant"] == "score_only":
            assert prediction_body["explanation"]["available"] is False
            assert prediction_body["explanation"]["top_features"] == []
        else:
            assert prediction_body["explanation"]["available"] is True


def test_sprint3_experiment_monitoring_history_and_retraining_ticket_flow() -> None:
    client, _ = _client()
    with client:
        bootstrap = client.post(
            "/api/v1/auth/register",
            json={"username": "admin", "password": "a-secure-password", "role": "admin"},
        )
        assert bootstrap.status_code == 201, bootstrap.text
        admin_token = _token(client, "admin", "a-secure-password")

        officer = client.post(
            "/api/v1/auth/register",
            headers=_headers(admin_token),
            json={
                "username": "officer",
                "password": "another-secure-password",
                "role": "loan_officer",
            },
        )
        assert officer.status_code == 201, officer.text
        officer_token = _token(client, "officer", "another-secure-password")

        analyst = client.post(
            "/api/v1/auth/register",
            headers=_headers(admin_token),
            json={
                "username": "analyst",
                "password": "a-third-secure-password",
                "role": "risk_analyst",
            },
        )
        assert analyst.status_code == 201, analyst.text
        analyst_token = _token(client, "analyst", "a-third-secure-password")

        assignment = client.get(
            "/api/v1/experiments/explanation-assignment",
            headers=_headers(officer_token),
        )
        assert assignment.status_code == 200, assignment.text
        assignment_body = assignment.json()
        assert assignment_body["variant"] in {"score_only", "explanation_shown"}
        repeated_assignment = client.get(
            "/api/v1/experiments/explanation-assignment",
            headers=_headers(officer_token),
        )
        assert repeated_assignment.json()["id"] == assignment_body["id"]
        assert (
            client.get(
                "/api/v1/experiments/explanation-assignment",
                headers=_headers(admin_token),
            ).status_code
            == 403
        )

        prediction = client.post(
            "/api/v1/predictions",
            headers=_headers(officer_token),
            json={"features": _features()},
        )
        assert prediction.status_code == 201, prediction.text
        prediction_body = prediction.json()
        assert prediction_body["study_variant"] == assignment_body["variant"]
        if assignment_body["variant"] == "score_only":
            assert prediction_body["explanation"]["available"] is False
            assert prediction_body["explanation"]["top_features"] == []
        else:
            assert prediction_body["explanation"]["available"] is True

        exposure = client.post(
            "/api/v1/experiments/explanation-exposures",
            headers=_headers(officer_token),
            json={"prediction_id": prediction_body["id"]},
        )
        assert exposure.status_code == 201, exposure.text
        exposure_body = exposure.json()
        assert exposure_body["variant"] == assignment_body["variant"]
        assert exposure_body["explanation_shown"] == (
            assignment_body["variant"] == "explanation_shown"
        )
        repeated_exposure = client.post(
            "/api/v1/experiments/explanation-exposures",
            headers=_headers(officer_token),
            json={"prediction_id": prediction_body["id"]},
        )
        assert repeated_exposure.json()["id"] == exposure_body["id"]

        assert (
            client.get("/api/v1/monitoring/history", headers=_headers(officer_token)).status_code
            == 403
        )
        initial_history = client.get("/api/v1/monitoring/history", headers=_headers(admin_token))
        assert initial_history.status_code == 200, initial_history.text
        assert any(
            item["source"] == "score_observation" for item in initial_history.json()["snapshots"]
        )

        drift = client.post(
            "/api/v1/monitoring/feature-drift",
            headers=_headers(admin_token),
            json={
                "reference_rows": [{"dti": 1.0}, {"dti": 1.1}, {"dti": 0.9}],
                "current_rows": [{"dti": 10.0}, {"dti": 11.0}, {"dti": 12.0}],
                "alpha": 0.5,
            },
        )
        assert drift.status_code == 200, drift.text
        assert drift.json()["status"] == "drift_detected"

        history = client.get("/api/v1/monitoring/history?limit=60", headers=_headers(admin_token))
        assert history.status_code == 200, history.text
        snapshots = history.json()["snapshots"]
        drift_snapshots = [
            item
            for item in snapshots
            if item["source"] == "feature_drift" and item["snapshot"]["status"] == "drift_detected"
        ]
        assert drift_snapshots
        assert drift_snapshots[-1]["snapshot"]["feature_results"][0]["feature"] == "dti"

        assert (
            client.post(
                "/api/v1/retraining-tickets",
                headers=_headers(officer_token),
                json={"reason": "KS drift requires review", "human_review_confirmed": True},
            ).status_code
            == 403
        )
        ticket = client.post(
            "/api/v1/retraining-tickets",
            headers=_headers(analyst_token),
            json={"reason": "KS drift requires review", "human_review_confirmed": True},
        )
        assert ticket.status_code == 201, ticket.text
        ticket_body = ticket.json()
        assert ticket_body["status"] == "open"
        assert ticket_body["monitoring_snapshot_id"] == drift_snapshots[-1]["id"]

        assert (
            client.post(
                f"/api/v1/retraining-tickets/{ticket_body['id']}/review",
                headers=_headers(analyst_token),
                json={"decision": "approve", "note": "Proceed through the manual workflow."},
            ).status_code
            == 403
        )
        reviewed = client.post(
            f"/api/v1/retraining-tickets/{ticket_body['id']}/review",
            headers=_headers(admin_token),
            json={"decision": "approve", "note": "Proceed through the manual workflow."},
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["status"] == "approved"
        assert reviewed.json()["reviewed_by_id"] == bootstrap.json()["id"]
        assert (
            client.post(
                f"/api/v1/retraining-tickets/{ticket_body['id']}/review",
                headers=_headers(admin_token),
                json={"decision": "reject"},
            ).status_code
            == 409
        )


def test_shap_service_defaults_to_five_contributors() -> None:
    class SixFeaturePredictor:
        def shap_values(self, features: pd.DataFrame) -> list[np.ndarray]:
            values = np.array([[0.9, 0.8, 0.7, 0.6, 0.5, 0.4]])
            return [np.zeros_like(values), values]

    features = pd.DataFrame(
        {name: [index] for index, name in enumerate(["a", "b", "c", "d", "e", "f"])}
    )
    result = SimpleNamespace(
        artifact=SimpleNamespace(predictor=SixFeaturePredictor()),
        model_features=features,
    )

    explanation = ShapService().explain(result)

    assert explanation.available is True
    assert len(explanation.top_features) == 5
    assert [item.feature for item in explanation.top_features] == ["a", "b", "c", "d", "e"]
