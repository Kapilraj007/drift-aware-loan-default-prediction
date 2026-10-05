"""API-level tests for Sprint 2 auth, persistence, scoring, and audit flows."""

from __future__ import annotations

import os
from collections.abc import Iterator
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.rbac import ROLE_PERMISSIONS, UserRole
from backend.app.core.security import hash_password, legacy_hash_password
from backend.app.db.seed import seed_demo_users, sync_catalogue
from backend.app.db.test_guard import UnsafeTestDatabaseError, require_test_database_url
from backend.app.main import create_app
from backend.app.models.db_models import ExplanationExperimentAssignment, User
from backend.app.services.drift_service import DriftService
from backend.app.services.inference_service import ModelArtifactError
from backend.app.services.shap_service import Explanation, FeatureAttribution, ShapService

try:
    TEST_DATABASE_URL = require_test_database_url()
except UnsafeTestDatabaseError as exc:
    pytest.skip(str(exc), allow_module_level=True)


@pytest.fixture(scope="module", autouse=True)
def migrated_test_database() -> Iterator[None]:
    previous = os.environ.get("DIRECT_DATABASE_URL")
    os.environ["DIRECT_DATABASE_URL"] = TEST_DATABASE_URL
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield
    finally:
        if previous is None:
            os.environ.pop("DIRECT_DATABASE_URL", None)
        else:
            os.environ["DIRECT_DATABASE_URL"] = previous


@pytest.fixture(autouse=True)
def clean_test_database() -> None:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    table_names = (
        "audit_events, role_permissions, permissions, roles, retraining_tickets, "
        "monitoring_snapshots, explanation_experiment_exposures, "
        "explanation_experiment_assignments, feedback, predictions, applications, users"
    )
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
    engine.dispose()


ADMIN_PASSWORD = "Admin@Test2026"
OFFICER_PASSWORD = "Officer@Test2026"
ANALYST_PASSWORD = "Analyst@Test2026"


def _seed_test_admin() -> None:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    with Session(engine) as session, session.begin():
        roles = sync_catalogue(session)
        session.add(
            User(
                username="admin",
                password_hash=hash_password(ADMIN_PASSWORD),
                role_id=roles[UserRole.ADMIN].id,
                email="admin@test.invalid",
                full_name="Test Administrator",
                is_active=True,
            )
        )
    engine.dispose()


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


class _UnavailableInferenceService:
    def predict(self, raw_features: dict[str, object]) -> SimpleNamespace:
        del raw_features
        raise ModelArtifactError('simulated missing model artifact')


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


def _client(
    *,
    cors_origins: tuple[str, ...] = (),
    seed_admin: bool = True,
    login_max_failures: int = 5,
) -> tuple[TestClient, _FakeInferenceService]:
    if seed_admin:
        _seed_test_admin()
    settings = Settings(
        login_max_failures=login_max_failures,
        database_url=TEST_DATABASE_URL,
        direct_database_url=TEST_DATABASE_URL,
        jwt_secret_key="test-secret-used-only-on-isolated-test-branch",
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


def _create_user(
    client: TestClient,
    admin_token: str,
    *,
    username: str,
    password: str,
    role: UserRole,
) -> dict[str, object]:
    response = client.post(
        '/api/v1/users',
        headers=_headers(admin_token),
        json={'username': username, 'password': password, 'role': role.value},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_study_variant(username: str, variant: str) -> None:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with Session(engine) as session, session.begin():
            user = session.scalar(select(User).where(User.username == username))
            assert user is not None
            assignment = session.scalar(
                select(ExplanationExperimentAssignment).where(
                    ExplanationExperimentAssignment.officer_id == user.id
                )
            )
            if assignment is None:
                session.add(
                    ExplanationExperimentAssignment(officer_id=user.id, variant=variant)
                )
            else:
                assignment.variant = variant
    finally:
        engine.dispose()


def test_backend_full_auditable_prediction_flow() -> None:
    client, inference = _client()
    with client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json()["status"] == "ready"

        # Administrative creation comes from the explicit seed, never registration.
        assert client.post("/api/v1/auth/register", json={}).status_code == 404
        admin_token = _token(client, "admin", ADMIN_PASSWORD)

        officer = client.post(
            "/api/v1/users",
            headers=_headers(admin_token),
            json={
                "username": "officer",
                "password": OFFICER_PASSWORD,
                "role": "loan_officer",
            },
        )
        assert officer.status_code == 201, officer.text
        officer_token = _token(client, "officer", OFFICER_PASSWORD)

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
        assert body["explanation"]["available"] is (
            body["study_variant"] == "explanation_shown"
        )
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
        token = _token(client, "admin", ADMIN_PASSWORD)
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
        admin_token = _token(client, "admin", ADMIN_PASSWORD)

        officer = client.post(
            "/api/v1/users",
            headers=_headers(admin_token),
            json={
                "username": "officer",
                "password": OFFICER_PASSWORD,
                "role": "loan_officer",
            },
        )
        assert officer.status_code == 201, officer.text
        officer_token = _token(client, "officer", OFFICER_PASSWORD)

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
        admin_token = _token(client, "admin", ADMIN_PASSWORD)
        bootstrap = client.get(
            "/api/v1/auth/me", headers=_headers(admin_token)
        ).json()

        officer = client.post(
            "/api/v1/users",
            headers=_headers(admin_token),
            json={
                "username": "officer",
                "password": OFFICER_PASSWORD,
                "role": "loan_officer",
            },
        )
        assert officer.status_code == 201, officer.text
        officer_token = _token(client, "officer", OFFICER_PASSWORD)

        analyst = client.post(
            "/api/v1/users",
            headers=_headers(admin_token),
            json={
                "username": "analyst",
                "password": ANALYST_PASSWORD,
                "role": "risk_analyst",
            },
        )
        assert analyst.status_code == 201, analyst.text
        analyst_token = _token(client, "analyst", ANALYST_PASSWORD)

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
        assert reviewed.json()["reviewed_by_id"] == bootstrap["id"]
        assert (
            client.post(
                f"/api/v1/retraining-tickets/{ticket_body['id']}/review",
                headers=_headers(admin_token),
                json={"decision": "reject"},
            ).status_code
            == 409
        )


def test_login_locks_at_the_configured_failure_threshold() -> None:
    client, _ = _client(login_max_failures=2)
    with client:
        for _ in range(2):
            response = client.post(
                '/api/v1/auth/login',
                json={'username': 'admin', 'password': 'wrong-password'},
            )
            assert response.status_code == 401
        assert (
            client.post(
                '/api/v1/auth/login',
                json={'username': 'admin', 'password': ADMIN_PASSWORD},
            ).status_code
            == 401
        )
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with Session(engine) as session:
            user = session.scalar(select(User).where(User.username == 'admin'))
            assert user is not None
            assert user.failed_login_count == 2
            assert user.locked_until is not None
    finally:
        engine.dispose()


def test_deactivation_and_admin_protections_apply_to_existing_tokens() -> None:
    client, _ = _client()
    with client:
        admin_token = _token(client, 'admin', ADMIN_PASSWORD)
        admin_id = client.get('/api/v1/auth/me', headers=_headers(admin_token)).json()['id']
        officer = _create_user(
            client,
            admin_token,
            username='deactivated-officer',
            password=OFFICER_PASSWORD,
            role=UserRole.LOAN_OFFICER,
        )
        officer_token = _token(client, 'deactivated-officer', OFFICER_PASSWORD)
        deactivated = client.patch(
            '/api/v1/users/' + str(officer['id']),
            headers=_headers(admin_token),
            json={'is_active': False},
        )
        assert deactivated.status_code == 200, deactivated.text
        assert client.get('/api/v1/auth/me', headers=_headers(officer_token)).status_code == 401

        self_deactivation = client.patch(
            '/api/v1/users/' + str(admin_id),
            headers=_headers(admin_token),
            json={'is_active': False},
        )
        assert self_deactivation.status_code == 409
        last_admin_demotion = client.patch(
            '/api/v1/users/' + str(admin_id),
            headers=_headers(admin_token),
            json={'role': UserRole.LOAN_OFFICER.value},
        )
        assert last_admin_demotion.status_code == 409
        assert client.get('/api/v1/auth/me', headers=_headers(admin_token)).status_code == 200


def test_successful_legacy_password_login_rehashes_to_argon2() -> None:
    client, _ = _client()
    with client:
        admin_token = _token(client, 'admin', ADMIN_PASSWORD)
        legacy = _create_user(
            client,
            admin_token,
            username='legacy-user',
            password=OFFICER_PASSWORD,
            role=UserRole.LOAN_OFFICER,
        )
        engine = create_engine(TEST_DATABASE_URL, future=True)
        try:
            with Session(engine) as session, session.begin():
                user = session.get(User, legacy['id'])
                assert user is not None
                user.password_hash = legacy_hash_password(OFFICER_PASSWORD)
            assert _token(client, 'legacy-user', OFFICER_PASSWORD)
            with Session(engine) as session:
                updated = session.get(User, legacy['id'])
                assert updated is not None
                assert updated.password_hash.startswith('$argon2')
        finally:
            engine.dispose()


def test_rbac_catalogue_seed_is_idempotent_and_complete() -> None:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with Session(engine) as session, session.begin():
            roles = sync_catalogue(session)
            assert set(roles) == set(UserRole)
            for role_name, expected_permissions in ROLE_PERMISSIONS.items():
                codes = {mapping.permission.code for mapping in roles[role_name].permissions}
                assert codes == {permission.value for permission in expected_permissions}
        with Session(engine) as session, session.begin():
            repeated = sync_catalogue(session)
            assert set(repeated) == set(UserRole)
    finally:
        engine.dispose()


def test_demo_user_seed_is_idempotent_and_assigns_both_study_arms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passwords = {
        "SEED_ADMIN_PASSWORD": "Admin@Test2026",
        "SEED_ANALYST_PASSWORD": "Analyst@Test2026",
        "SEED_OFFICER_EXPLAIN_PASSWORD": "Officer1@Test2026",
        "SEED_OFFICER_SCOREONLY_PASSWORD": "Officer2@Test2026",
    }
    for name, value in passwords.items():
        monkeypatch.setenv(name, value)

    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with Session(engine) as session, session.begin():
            roles = sync_catalogue(session)
            first = seed_demo_users(session, roles)
            original = {
                user.username: (user.id, user.password_hash)
                for user in first
            }
            repeated = seed_demo_users(session, roles)
            assert {
                user.username: (user.id, user.password_hash)
                for user in repeated
            } == original

            assignments = dict(
                session.execute(
                    select(User.username, ExplanationExperimentAssignment.variant)
                    .join(
                        ExplanationExperimentAssignment,
                        ExplanationExperimentAssignment.officer_id == User.id,
                    )
                    .where(User.username.like("officer.%"))
                ).all()
            )
            assert assignments == {
                "officer.explain": "explanation_shown",
                "officer.scoreonly": "score_only",
            }
    finally:
        engine.dispose()


def test_authentication_has_no_public_registration_and_uses_current_identity() -> None:
    client, _ = _client()
    with client:
        assert client.get('/api/v1/auth/me').status_code == 401
        assert (
            client.post(
                '/api/v1/auth/login',
                json={'username': 'admin', 'password': 'not-the-password'},
            ).status_code
            == 401
        )
        assert client.post('/api/v1/auth/register', json={}).status_code == 404

        admin_token = _token(client, 'admin', ADMIN_PASSWORD)
        identity = client.get('/api/v1/auth/me', headers=_headers(admin_token))
        assert identity.status_code == 200, identity.text
        assert identity.json()['username'] == 'admin'
        assert identity.json()['role'] == UserRole.ADMIN.value
        assert 'user:manage' in identity.json()['permissions']

        changed_password = 'ChangedAdmin@Test2026'
        changed = client.post(
            '/api/v1/auth/change-password',
            headers=_headers(admin_token),
            json={'current_password': ADMIN_PASSWORD, 'new_password': changed_password},
        )
        assert changed.status_code == 204, changed.text
        assert (
            client.post(
                '/api/v1/auth/login',
                json={'username': 'admin', 'password': ADMIN_PASSWORD},
            ).status_code
            == 401
        )
        assert _token(client, 'admin', changed_password)


def test_rbac_and_ownership_block_cross_officer_access() -> None:
    client, _ = _client()
    with client:
        admin_token = _token(client, 'admin', ADMIN_PASSWORD)
        _create_user(
            client,
            admin_token,
            username='owner',
            password=OFFICER_PASSWORD,
            role=UserRole.LOAN_OFFICER,
        )
        _create_user(
            client,
            admin_token,
            username='peer',
            password='PeerOfficer@Test2026',
            role=UserRole.LOAN_OFFICER,
        )
        _create_user(
            client,
            admin_token,
            username='analyst',
            password=ANALYST_PASSWORD,
            role=UserRole.RISK_ANALYST,
        )
        owner_token = _token(client, 'owner', OFFICER_PASSWORD)
        peer_token = _token(client, 'peer', 'PeerOfficer@Test2026')
        analyst_token = _token(client, 'analyst', ANALYST_PASSWORD)

        application = client.post(
            '/api/v1/applications',
            headers=_headers(owner_token),
            json={'external_reference': 'owned-case', 'features': _features()},
        )
        assert application.status_code == 201, application.text
        application_id = application.json()['id']
        prediction = client.post(
            '/api/v1/predictions',
            headers=_headers(owner_token),
            json={'application_id': application_id},
        )
        assert prediction.status_code == 201, prediction.text
        prediction_id = prediction.json()['id']

        assert client.get('/api/v1/users', headers=_headers(peer_token)).status_code == 403
        assert client.get('/api/v1/roles', headers=_headers(peer_token)).status_code == 403
        assert (
            client.get('/api/v1/monitoring/history', headers=_headers(peer_token)).status_code
            == 403
        )
        assert (
            client.get(
                f'/api/v1/applications/{application_id}', headers=_headers(peer_token)
            ).status_code
            == 403
        )
        assert (
            client.get(
                f'/api/v1/applications/{application_id}/review', headers=_headers(peer_token)
            ).status_code
            == 403
        )
        assert (
            client.post(
                '/api/v1/predictions',
                headers=_headers(peer_token),
                json={'application_id': application_id},
            ).status_code
            == 403
        )
        assert (
            client.get(
                f'/api/v1/predictions/{prediction_id}', headers=_headers(peer_token)
            ).status_code
            == 403
        )
        assert (
            client.post(
                '/api/v1/feedback',
                headers=_headers(peer_token),
                json={
                    'prediction_id': prediction_id,
                    'decision': 'approve',
                    'agreed_with_model': True,
                },
            ).status_code
            == 403
        )
        assert client.get('/api/v1/applications', headers=_headers(peer_token)).json()['total'] == 0
        assert client.get('/api/v1/predictions', headers=_headers(peer_token)).json()['total'] == 0

        assert (
            client.get(
                f'/api/v1/applications/{application_id}', headers=_headers(analyst_token)
            ).status_code
            == 200
        )
        assert (
            client.get(
                f'/api/v1/predictions/{prediction_id}', headers=_headers(analyst_token)
            ).status_code
            == 200
        )


def test_feedback_amendment_and_override_require_explanatory_notes() -> None:
    client, _ = _client()
    with client:
        admin_token = _token(client, 'admin', ADMIN_PASSWORD)
        _create_user(
            client,
            admin_token,
            username='feedback-officer',
            password=OFFICER_PASSWORD,
            role=UserRole.LOAN_OFFICER,
        )
        officer_token = _token(client, 'feedback-officer', OFFICER_PASSWORD)
        scored = client.post(
            '/api/v1/predictions',
            headers=_headers(officer_token),
            json={'features': _features()},
        )
        assert scored.status_code == 201, scored.text
        prediction_id = scored.json()['id']

        first = client.post(
            '/api/v1/feedback',
            headers=_headers(officer_token),
            json={
                'prediction_id': prediction_id,
                'decision': 'approve',
                'agreed_with_model': True,
            },
        )
        assert first.status_code == 201, first.text
        assert first.json()['version'] == 1
        assert first.json()['amends_feedback_id'] is None

        missing_amendment_note = client.post(
            '/api/v1/feedback',
            headers=_headers(officer_token),
            json={
                'prediction_id': prediction_id,
                'decision': 'decline',
                'agreed_with_model': True,
            },
        )
        assert missing_amendment_note.status_code == 422
        assert missing_amendment_note.json()['detail'][0]['field'] == 'note'

        amendment = client.post(
            '/api/v1/feedback',
            headers=_headers(officer_token),
            json={
                'prediction_id': prediction_id,
                'decision': 'decline',
                'agreed_with_model': True,
                'note': 'Corrected after reviewing new documentation.',
            },
        )
        assert amendment.status_code == 201, amendment.text
        assert amendment.json()['version'] == 2
        assert amendment.json()['amends_feedback_id'] == first.json()['id']

        override_score = client.post(
            '/api/v1/predictions',
            headers=_headers(officer_token),
            json={'features': _features()},
        )
        assert override_score.status_code == 201, override_score.text
        override_id = override_score.json()['id']
        missing_override_note = client.post(
            '/api/v1/feedback',
            headers=_headers(officer_token),
            json={
                'prediction_id': override_id,
                'decision': 'approve',
                'agreed_with_model': False,
            },
        )
        assert missing_override_note.status_code == 422
        assert missing_override_note.json()['detail'][0]['field'] == 'note'
        override = client.post(
            '/api/v1/feedback',
            headers=_headers(officer_token),
            json={
                'prediction_id': override_id,
                'decision': 'approve',
                'agreed_with_model': False,
                'note': 'Income documents justify the exception.',
            },
        )
        assert override.status_code == 201, override.text
        assert override.json()['note'] == 'Income documents justify the exception.'


def test_restart_rehydrates_persisted_score_and_drift_state() -> None:
    client, _ = _client()
    with client:
        admin_token = _token(client, 'admin', ADMIN_PASSWORD)
        prediction = client.post(
            '/api/v1/predictions',
            headers=_headers(admin_token),
            json={'features': _features()},
        )
        assert prediction.status_code == 201, prediction.text
        drift = client.post(
            '/api/v1/monitoring/feature-drift',
            headers=_headers(admin_token),
            json={
                'reference_rows': [{'dti': 1.0}, {'dti': 1.1}, {'dti': 0.9}],
                'current_rows': [{'dti': 10.0}, {'dti': 11.0}, {'dti': 12.0}],
                'alpha': 0.5,
            },
        )
        assert drift.status_code == 200, drift.text
        assert drift.json()['status'] == 'drift_detected'

    restarted, _ = _client(seed_admin=False)
    with restarted:
        status = restarted.get('/api/v1/monitoring/status', headers=_headers(admin_token))
        assert status.status_code == 200, status.text
        assert status.json()['status'] == 'drift_detected'
        assert status.json()['score_stream_count'] == 1


def test_field_validation_and_simulated_503_paths_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    with client:
        admin_token = _token(client, 'admin', ADMIN_PASSWORD)
        invalid_features = _features()
        invalid_features['annual_inc'] = 'not-a-number'
        invalid = client.post(
            '/api/v1/predictions',
            headers=_headers(admin_token),
            json={'features': invalid_features},
        )
        assert invalid.status_code == 422
        assert invalid.json()['error'] == 'validation_error'
        assert any(item['field'] == 'features.annual_inc' for item in invalid.json()['detail'])

        client.app.state.inference_service = _UnavailableInferenceService()
        model_unavailable = client.post(
            '/api/v1/predictions',
            headers=_headers(admin_token),
            json={'features': _features()},
        )
        assert model_unavailable.status_code == 503
        assert 'Model is not ready for scoring' in model_unavailable.json()['detail']

        def unavailable_session() -> Session:
            raise OperationalError('SELECT 1', {}, RuntimeError('simulated database wake'))

        monkeypatch.setattr(client.app.state.database, 'session', unavailable_session)
        database_waking = client.get('/api/v1/auth/me', headers=_headers(admin_token))
        assert database_waking.status_code == 503
        assert database_waking.json()['error'] == 'database_waking'
        assert database_waking.headers['Retry-After'] == '3'


def test_score_only_variant_masks_explanations_on_every_prediction_read() -> None:
    client, _ = _client()
    with client:
        admin_token = _token(client, 'admin', ADMIN_PASSWORD)
        _create_user(
            client,
            admin_token,
            username='scoreonly',
            password=OFFICER_PASSWORD,
            role=UserRole.LOAN_OFFICER,
        )
        _set_study_variant('scoreonly', 'score_only')
        officer_token = _token(client, 'scoreonly', OFFICER_PASSWORD)

        application = client.post(
            '/api/v1/applications',
            headers=_headers(officer_token),
            json={'external_reference': 'score-only-case', 'features': _features()},
        )
        assert application.status_code == 201, application.text
        application_id = application.json()['id']

        created = client.post(
            '/api/v1/predictions',
            headers=_headers(officer_token),
            json={'application_id': application_id},
        )
        assert created.status_code == 201, created.text
        prediction = created.json()
        assert prediction['study_variant'] == 'score_only'
        assert prediction['explanation']['available'] is False
        assert prediction['explanation']['top_features'] == []

        fetched = client.get(
            '/api/v1/predictions/' + str(prediction['id']), headers=_headers(officer_token)
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()['explanation']['available'] is False
        listed = client.get('/api/v1/predictions', headers=_headers(officer_token))
        assert listed.status_code == 200, listed.text
        assert listed.json()['items'][0]['explanation']['available'] is False
        review = client.get(
            '/api/v1/applications/' + str(application_id) + '/review',
            headers=_headers(officer_token),
        )
        assert review.status_code == 200, review.text
        assert review.json()['latest_prediction']['explanation']['available'] is False


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
