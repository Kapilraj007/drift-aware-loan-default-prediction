"""PostgreSQL engine, migration-state, and request-session lifecycle."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import Settings, normalize_postgres_url

LOGGER = logging.getLogger(__name__)


def create_direct_engine(
    url: str,
    *,
    connect_timeout_seconds: int = 15,
) -> Engine:
    """Create an administrative engine; direct connections may auto-prepare."""

    return create_engine(
        normalize_postgres_url(url),
        future=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )


def expected_migration_head(config_path: str | Path = "alembic.ini") -> str:
    config = Config(str(config_path))
    return ScriptDirectory.from_config(config).get_current_head() or ""


def current_migration_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def migration_is_current(engine: Engine) -> tuple[bool, str | None, str]:
    current = current_migration_revision(engine)
    expected = expected_migration_head()
    return current == expected, current, expected


class Database:
    """Own the small runtime pool used behind Neon's transaction pooler."""

    def __init__(self, settings: Settings) -> None:
        self.engine = create_engine(
            settings.database_url,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
            connect_args={
                "connect_timeout": settings.db_connect_timeout_seconds,
                "prepare_threshold": None,
            },
        )
        self._connect_retries = settings.db_connect_retries
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )

    def connect_with_retry(self) -> float:
        """Wake a suspended Neon compute with bounded exponential backoff."""

        started = time.perf_counter()
        for attempt in range(1, self._connect_retries + 1):
            try:
                with self.engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                return (time.perf_counter() - started) * 1_000
            except Exception:
                if attempt >= self._connect_retries:
                    raise
                delay = min(2 ** (attempt - 1), 8)
                LOGGER.warning(
                    "Database connection attempt %d/%d failed; Neon compute may be "
                    "waking from idle. Retrying in %d second(s).",
                    attempt,
                    self._connect_retries,
                    delay,
                )
                time.sleep(delay)
        raise RuntimeError("Database retry loop exited unexpectedly")

    def require_current_migrations(self) -> None:
        current, actual, expected = migration_is_current(self.engine)
        if not current:
            actual_text = actual or "none"
            raise RuntimeError(
                "Database migration state is not current "
                f"(database={actual_text}, expected={expected}). "
                "Run 'alembic upgrade head' using DIRECT_DATABASE_URL."
            )

    def session(self) -> Session:
        return self._session_factory()

    def dispose(self) -> None:
        self.engine.dispose()


def get_session(request: Request) -> Generator[Session, None, None]:
    """Yield a request-scoped transaction and roll it back on errors."""

    database: Database = request.app.state.database
    session = database.session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
