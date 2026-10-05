"""Fast unit checks for TLS normalization and destructive-test guards."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings, normalize_postgres_url
from backend.app.db.seed import main as seed_main
from backend.app.db.session import expected_migration_head
from backend.app.db.test_guard import UnsafeTestDatabaseError, require_test_database_url
from backend.app.main import create_app


def test_database_url_normalization_adds_psycopg_and_tls() -> None:
    normalized = normalize_postgres_url(
        "postgresql://user:pass@ep-example.aws.neon.tech/neondb"
    )
    assert normalized.startswith("postgresql+psycopg://")
    assert "sslmode=require" in normalized


def test_database_url_normalization_rejects_disabled_tls() -> None:
    with pytest.raises(ValueError, match="must not use sslmode=disable"):
        normalize_postgres_url(
            "postgresql://user:pass@ep-example.aws.neon.tech/neondb?sslmode=disable"
        )


def test_alembic_head_fits_default_version_column() -> None:
    head = expected_migration_head()
    assert head == "0003_rbac_feedback_history"
    assert len(head) <= 32


def test_test_guard_refuses_showcase_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    showcase = (
        "postgresql://user:pass@ep-main.aws.neon.tech/neondb?sslmode=require"
    )
    monkeypatch.setenv("DATABASE_URL", showcase)
    monkeypatch.setenv("DIRECT_DATABASE_URL", showcase)
    monkeypatch.setenv("TEST_DATABASE_URL", showcase)
    with pytest.raises(UnsafeTestDatabaseError, match="same endpoint"):
        require_test_database_url()


def test_demo_seed_refuses_production_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SEED_DEMO_USERS", "true")
    with pytest.raises(RuntimeError, match="refused when APP_ENV=production"):
        seed_main(["--demo-users", "--yes"])


def test_healthz_does_not_open_a_database_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        database_url=normalize_postgres_url(
            "postgresql://user:pass@ep-unit-pooler.aws.neon.tech/neondb"
        ),
        direct_database_url=normalize_postgres_url(
            "postgresql://user:pass@ep-unit.aws.neon.tech/neondb"
        ),
        jwt_secret_key="unit-test-secret-that-is-never-deployed",
    )
    app = create_app(settings)

    def fail_if_connected() -> None:
        raise AssertionError("/healthz must not connect to the database")

    monkeypatch.setattr(app.state.database.engine, "connect", fail_if_connected)
    client = TestClient(app)
    try:
        assert client.get("/healthz").json() == {"status": "ok"}
    finally:
        client.close()
        app.state.database.dispose()
