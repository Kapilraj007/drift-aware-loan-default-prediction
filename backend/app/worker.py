"""Optional Celery worker entry point for the Docker Compose queue profile.

This module is intentionally never imported by :mod:`backend.app.main`, so a
normal API process remains usable with SQLite and no Redis service.  The worker
is activated only by ``python -m backend.app.worker`` (or deployment tooling
that imports :func:`create_celery_app`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def create_celery_app() -> Any:
    """Create the optional queue app only in a queue-worker process."""

    try:
        from celery import Celery
    except ImportError as exc:
        raise RuntimeError(
            "The queue worker requires the optional 'celery' dependency. "
            "The FastAPI API does not require it."
        ) from exc

    broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    result_backend = os.getenv("CELERY_RESULT_BACKEND", broker_url)
    celery_app = Celery("drift_aware_loan", broker=broker_url, backend=result_backend)
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )

    @celery_app.task(name="backend.app.worker.healthcheck")
    def healthcheck() -> dict[str, str]:
        """A non-mutating task used to verify the queue profile wiring."""

        return {"status": "ok"}

    return celery_app


def main() -> None:
    """Run a Celery worker without changing API startup requirements."""

    worker = create_celery_app()
    worker.worker_main(["worker", "--loglevel=" + os.getenv("CELERY_LOG_LEVEL", "INFO")])


if __name__ == "__main__":  # pragma: no cover - exercised by deployment, not API tests
    main()
