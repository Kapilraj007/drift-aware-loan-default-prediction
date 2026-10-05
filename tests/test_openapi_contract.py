"""Executable OpenAPI-to-frontend operation contract."""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.config import Settings, normalize_postgres_url
from backend.app.main import create_app

Operation = tuple[str, str]

UI_OPERATIONS: frozenset[Operation] = frozenset(
    {
        ("post", "/api/v1/auth/login"),
        ("get", "/api/v1/auth/me"),
        ("post", "/api/v1/auth/change-password"),
        ("get", "/api/v1/reference/application-schema"),
        ("post", "/api/v1/applications"),
        ("get", "/api/v1/applications"),
        ("get", "/api/v1/applications/{application_id}"),
        ("get", "/api/v1/applications/{application_id}/review"),
        ("post", "/api/v1/predictions"),
        ("get", "/api/v1/predictions"),
        ("get", "/api/v1/predictions/{prediction_id}"),
        ("post", "/api/v1/feedback"),
        ("get", "/api/v1/feedback"),
        ("get", "/api/v1/experiments/explanation-assignment"),
        ("post", "/api/v1/experiments/explanation-exposures"),
        ("get", "/api/v1/experiments/summary"),
        ("get", "/api/v1/dashboard/summary"),
        ("get", "/api/v1/monitoring/status"),
        ("get", "/api/v1/monitoring/history"),
        ("post", "/api/v1/monitoring/feature-drift"),
        ("get", "/api/v1/retraining-tickets"),
        ("post", "/api/v1/retraining-tickets"),
        ("post", "/api/v1/retraining-tickets/{ticket_id}/review"),
        ("get", "/api/v1/model"),
        ("get", "/api/v1/training-runs"),
        ("get", "/api/v1/users"),
        ("post", "/api/v1/users"),
        ("patch", "/api/v1/users/{user_id}"),
        ("post", "/api/v1/users/{user_id}/reset-password"),
        ("get", "/api/v1/roles"),
        ("get", "/api/v1/audit-events"),
    }
)
DOCUMENTED_NON_UI_OPERATIONS: frozenset[Operation] = frozenset(
    {
        ("get", "/api/v1/users/{user_id}"),
        ("get", "/healthz"),
        ("get", "/readyz"),
    }
)


def _generated_openapi() -> dict[str, object]:
    settings = Settings(
        database_url=normalize_postgres_url(
            "postgresql://user:pass@ep-contract-pooler.neon.tech/unit"
        ),
        direct_database_url=normalize_postgres_url(
            "postgresql://user:pass@ep-contract.neon.tech/unit"
        ),
        jwt_secret_key="openapi-contract-secret-0000000001",
    )
    app = create_app(settings)
    try:
        return app.openapi()
    finally:
        app.state.database.dispose()


def _operations(document: dict[str, object]) -> frozenset[Operation]:
    paths = document["paths"]
    assert isinstance(paths, dict)
    return frozenset(
        (method, path)
        for path, path_item in paths.items()
        if isinstance(path_item, dict)
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete"}
    )


def test_committed_openapi_and_full_stack_operation_map_are_current() -> None:
    generated = _generated_openapi()
    committed = json.loads(Path("openapi.json").read_text(encoding="utf-8"))
    assert committed == generated, "run: python scripts/export_openapi.py"

    operations = _operations(generated)
    assert UI_OPERATIONS <= operations
    assert operations - UI_OPERATIONS == DOCUMENTED_NON_UI_OPERATIONS

