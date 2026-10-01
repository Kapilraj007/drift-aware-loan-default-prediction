"""SQLAlchemy session lifecycle with SQLite-friendly defaults."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..models.db_models import Base


class Database:
    """Owns an engine and session factory for one FastAPI application."""

    def __init__(self, url: str) -> None:
        connect_args: dict[str, object] = {}
        engine_kwargs: dict[str, object] = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            # A bare sqlite:// URL is useful for fast TestClient suites.  A
            # StaticPool makes every request use the same in-memory database.
            if url in {"sqlite://", "sqlite+pysqlite://", "sqlite:///:memory:"}:
                engine_kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_schema(self) -> None:
        Base.metadata.drop_all(self.engine)

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
