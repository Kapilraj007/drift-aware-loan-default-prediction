"""FastAPI application factory for Sprint 2 decision-support services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from .api.v1.router import api_router
from .core.config import Settings
from .core.security import UserRole, hash_password
from .db.session import Database
from .models.db_models import User
from .services.drift_service import DriftService
from .services.inference_service import InferenceService, ModelArtifactError
from .services.shap_service import ShapService


def _bootstrap_admin(database: Database, settings: Settings) -> None:
    """Create an explicit environment-configured admin if no user exists."""

    if not settings.bootstrap_admin_username or not settings.bootstrap_admin_password:
        return
    with database.session() as session:
        if session.scalar(select(User.id).limit(1)) is not None:
            return
        session.add(
            User(
                username=settings.bootstrap_admin_username,
                password_hash=hash_password(settings.bootstrap_admin_password),
                role=UserRole.ADMIN.value,
            )
        )
        session.commit()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an isolated app instance for production, tests, or local development."""

    resolved_settings = settings or Settings.from_environment()
    database = Database(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database.create_schema()
        _bootstrap_admin(database, resolved_settings)
        yield
        database.dispose()

    app = FastAPI(
        title="Drift Aware Loan Default API",
        version="0.2.0",
        description=(
            "Human-in-the-loop loan default decision support with auditable "
            "model scores, explanations, officer feedback, and drift state."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    if resolved_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.inference_service = InferenceService(resolved_settings)
    app.state.shap_service = ShapService()
    app.state.drift_service = DriftService(resolved_settings)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/healthz", tags=["operations"])
    def healthz() -> dict[str, str]:
        """Liveness probe: the HTTP process is responsive."""

        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"])
    def readyz(response: Response) -> dict[str, object]:
        """Readiness probe: database and lazily loaded model must both work."""

        database_ready = True
        try:
            with database.session() as session:
                session.execute(text("SELECT 1"))
        except Exception:
            database_ready = False
        model_ready = True
        model_detail: str | None = None
        try:
            app.state.inference_service.describe()
        except ModelArtifactError as exc:
            model_ready = False
            model_detail = str(exc)
        if database_ready and model_ready:
            return {"status": "ready", "database": "ready", "model": "ready"}
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "database": "ready" if database_ready else "unavailable",
            "model": "ready" if model_ready else "unavailable",
            "detail": model_detail,
        }

    return app


app = create_app()
