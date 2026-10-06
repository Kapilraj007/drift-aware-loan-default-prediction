"""FastAPI application factory for local decision support backed by Neon."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.v1.router import api_router
from .core.config import Settings
from .db.session import Database, migration_is_current
from .models.db_models import MonitoringSnapshot, Prediction
from .services.drift_service import DriftService
from .services.inference_service import InferenceService, ModelArtifactError
from .services.shap_service import ShapService

LOGGER = logging.getLogger(__name__)


def _rehydrate_drift(
    database: Database,
    drift_service: DriftService,
    *,
    limit: int,
) -> int:
    """Replay a bounded score window and restore the latest persisted KS state."""

    with database.session() as session:
        descending_scores = list(
            session.scalars(
                select(Prediction.score)
                .order_by(Prediction.created_at.desc())
                .limit(limit)
            )
        )
        latest = session.scalar(
            select(MonitoringSnapshot)
            .order_by(MonitoringSnapshot.created_at.desc())
            .limit(1)
        )
    drift_service.rehydrate(
        list(reversed(descending_scores)),
        dict(latest.snapshot) if latest is not None else None,
    )
    return len(descending_scores)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an app whose startup checks connectivity and Alembic state."""

    resolved_settings = settings or Settings.from_environment()
    database = Database(resolved_settings)
    inference_service = InferenceService(resolved_settings)
    shap_service = ShapService()
    drift_service = DriftService(resolved_settings)
    logging.getLogger().setLevel(
        getattr(logging, resolved_settings.log_level, logging.INFO)
    )
    if resolved_settings.web_concurrency > 1:
        LOGGER.warning(
            "WEB_CONCURRENCY=%d; the showcase drift detector is process-local. "
            "Use one worker for consistent live state.",
            resolved_settings.web_concurrency,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        wake_latency_ms = database.connect_with_retry()
        database.require_current_migrations()
        replayed = _rehydrate_drift(
            database,
            app.state.drift_service,
            limit=resolved_settings.drift_rehydrate_limit,
        )
        LOGGER.info(
            "startup_ready database_wake_ms=%.1f drift_scores_replayed=%d",
            wake_latency_ms,
            replayed,
        )
        yield
        database.dispose()

    app = FastAPI(
        title="Drift Aware Loan Default API",
        version="1.0.0",
        description=(
            "Human-in-the-loop loan default decision support with auditable "
            "model scores, explanations, officer feedback, and drift state. "
            "Decision support only; a qualified human makes the final decision."
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
    app.state.inference_service = inference_service
    app.state.shap_service = shap_service
    app.state.drift_service = drift_service
    app.include_router(api_router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "").strip()
        if (
            not request_id
            or len(request_id) > 128
            or not all(character.isalnum() or character in "-_." for character in request_id)
        ):
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        LOGGER.info(
            "request_complete request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1_000,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details: list[dict[str, str]] = []
        for error in exc.errors():
            location = [str(part) for part in error.get("loc", ()) if part != "body"]
            message = str(error.get("msg", "Invalid value")).removeprefix("Value error, ")
            if not location:
                location = [
                    next(
                        (
                            field
                            for field in (
                                "earliest_cr_line",
                                "sub_grade",
                                "application_id",
                                "features",
                            )
                            if field in message
                        ),
                        "request",
                    )
                ]
            details.append(
                {
                    "field": ".".join(location) or "request",
                    "message": message,
                }
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            headers={"X-Request-ID": getattr(request.state, "request_id", "")},
            content={"error": "validation_error", "detail": details},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        codes = {
            400: "bad_request",
            401: "authentication_required",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
            503: "service_unavailable",
        }
        headers = dict(exc.headers or {})
        headers["X-Request-ID"] = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={
                "error": codes.get(exc.status_code, "request_error"),
                "detail": exc.detail,
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def database_unavailable(
        request: Request, exc: OperationalError | InterfaceError
    ) -> JSONResponse:
        del exc
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "3"},
            content={
                "error": "database_waking",
                "request_id": getattr(request.state, "request_id", None),
                "detail": (
                    "The database is temporarily unavailable and may be waking "
                    "from idle. Please retry shortly."
                ),
            },
        )

    @app.get("/healthz", tags=["operations"])
    def healthz() -> dict[str, str]:
        """Process liveness only. This endpoint deliberately never touches Neon."""

        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"])
    def readyz() -> JSONResponse:
        """Manual readiness check; clients must not poll this endpoint."""

        database_ready = False
        migration_ready = False
        database_latency_ms: float | None = None
        current_revision: str | None = None
        expected_revision: str | None = None
        database_detail: str | None = None
        started = time.perf_counter()
        try:
            with database.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            database_latency_ms = round((time.perf_counter() - started) * 1_000, 1)
            database_ready = True
            migration_ready, current_revision, expected_revision = migration_is_current(
                database.engine
            )
        except Exception:
            database_detail = (
                "Database unavailable; Neon compute may be waking from idle. Retry shortly."
            )

        model_ready = True
        model_detail: str | None = None
        try:
            app.state.inference_service.describe()
        except ModelArtifactError as exc:
            model_ready = False
            model_detail = str(exc)

        ready = database_ready and migration_ready and model_ready
        body = {
            "status": "ready" if ready else "not_ready",
            "database": {
                "status": "ready" if database_ready else "unavailable",
                "latency_ms": database_latency_ms,
                "detail": database_detail,
            },
            "migrations": {
                "status": "current" if migration_ready else "behind",
                "current": current_revision,
                "expected": expected_revision,
                "detail": None if migration_ready else "Run 'alembic upgrade head'.",
            },
            "model": {
                "status": "ready" if model_ready else "unavailable",
                "detail": model_detail,
            },
        }
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body,
        )

    return app
