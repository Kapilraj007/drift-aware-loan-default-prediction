"""Destructive integration checks restricted to the dedicated Neon test branch."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from backend.app.db.test_guard import (
    UnsafeTestDatabaseError,
    pooled_url_for_test_branch,
    require_test_database_url,
)

try:
    TEST_DATABASE_URL = require_test_database_url()
except UnsafeTestDatabaseError as exc:
    pytest.skip(str(exc), allow_module_level=True)


def test_migration_round_trip_on_isolated_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIRECT_DATABASE_URL", TEST_DATABASE_URL)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_alembic_models_and_migrations_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIRECT_DATABASE_URL", TEST_DATABASE_URL)
    command.check(Config("alembic.ini"))


def test_test_branch_pooler_handles_repeated_queries() -> None:
    pooled_url = pooled_url_for_test_branch(TEST_DATABASE_URL)
    engine = create_engine(
        pooled_url,
        future=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 15, "prepare_threshold": None},
    )
    try:
        with engine.connect() as connection:
            for _ in range(25):
                assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()
