"""Database-free authorization contract for every versioned API operation."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from fastapi.routing import APIRoute

from backend.app.core.config import Settings, normalize_postgres_url
from backend.app.core.rbac import ROLE_PERMISSIONS, PermissionCode, UserRole
from backend.app.main import create_app
from backend.app.models.db_models import Permission, Role, RolePermission, User

Operation = tuple[str, str]
Requirement = tuple[str, frozenset[PermissionCode]]

PUBLIC_OPERATIONS: frozenset[Operation] = frozenset(
    {("POST", "/api/v1/auth/login")}
)
IDENTITY_OPERATIONS: frozenset[Operation] = frozenset(
    {
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/change-password"),
    }
)
EXPECTED_PERMISSIONS: dict[Operation, Requirement] = {
    ("POST", "/api/v1/applications"): ("all", frozenset({PermissionCode.APPLICATION_CREATE})),
    ("GET", "/api/v1/applications"): (
        "any",
        frozenset(
            {PermissionCode.APPLICATION_READ_OWN, PermissionCode.APPLICATION_READ_ALL}
        ),
    ),
    ("GET", "/api/v1/applications/{application_id}/review"): (
        "any",
        frozenset(
            {PermissionCode.APPLICATION_READ_OWN, PermissionCode.APPLICATION_READ_ALL}
        ),
    ),
    ("GET", "/api/v1/applications/{application_id}"): (
        "any",
        frozenset(
            {PermissionCode.APPLICATION_READ_OWN, PermissionCode.APPLICATION_READ_ALL}
        ),
    ),
    ("POST", "/api/v1/predictions"): ("all", frozenset({PermissionCode.PREDICTION_CREATE})),
    ("GET", "/api/v1/predictions"): (
        "any",
        frozenset({PermissionCode.PREDICTION_READ_OWN, PermissionCode.PREDICTION_READ_ALL}),
    ),
    ("GET", "/api/v1/predictions/{prediction_id}"): (
        "any",
        frozenset({PermissionCode.PREDICTION_READ_OWN, PermissionCode.PREDICTION_READ_ALL}),
    ),
    ("POST", "/api/v1/feedback"): ("all", frozenset({PermissionCode.FEEDBACK_CREATE})),
    ("GET", "/api/v1/feedback"): (
        "any",
        frozenset({PermissionCode.FEEDBACK_READ_OWN, PermissionCode.FEEDBACK_READ_ALL}),
    ),
    ("GET", "/api/v1/experiments/explanation-assignment"): (
        "all",
        frozenset({PermissionCode.EXPERIMENT_PARTICIPATE}),
    ),
    ("POST", "/api/v1/experiments/explanation-exposures"): (
        "all",
        frozenset({PermissionCode.EXPERIMENT_PARTICIPATE}),
    ),
    ("GET", "/api/v1/experiments/summary"): (
        "all",
        frozenset({PermissionCode.EXPERIMENT_READ_RESULTS}),
    ),
    ("GET", "/api/v1/monitoring/history"): ("all", frozenset({PermissionCode.MONITORING_READ})),
    ("GET", "/api/v1/monitoring/status"): ("all", frozenset({PermissionCode.MONITORING_READ})),
    ("POST", "/api/v1/monitoring/feature-drift"): (
        "all",
        frozenset({PermissionCode.MONITORING_RUN_CHECK}),
    ),
    ("POST", "/api/v1/retraining-tickets"): ("all", frozenset({PermissionCode.RETRAINING_CREATE})),
    ("GET", "/api/v1/retraining-tickets"): ("all", frozenset({PermissionCode.RETRAINING_READ})),
    ("POST", "/api/v1/retraining-tickets/{ticket_id}/review"): (
        "all",
        frozenset({PermissionCode.RETRAINING_REVIEW}),
    ),
    ("GET", "/api/v1/model"): ("all", frozenset({PermissionCode.MODEL_READ})),
    ("GET", "/api/v1/training-runs"): ("all", frozenset({PermissionCode.MODEL_READ})),
    ("GET", "/api/v1/dashboard/summary"): ("all", frozenset({PermissionCode.DASHBOARD_READ})),
    ("GET", "/api/v1/reference/application-schema"): (
        "all",
        frozenset({PermissionCode.APPLICATION_CREATE}),
    ),
    ("GET", "/api/v1/users"): ("all", frozenset({PermissionCode.USER_MANAGE})),
    ("POST", "/api/v1/users"): ("all", frozenset({PermissionCode.USER_MANAGE})),
    ("GET", "/api/v1/users/{user_id}"): ("all", frozenset({PermissionCode.USER_MANAGE})),
    ("PATCH", "/api/v1/users/{user_id}"): ("all", frozenset({PermissionCode.USER_MANAGE})),
    ("POST", "/api/v1/users/{user_id}/reset-password"): (
        "all",
        frozenset({PermissionCode.USER_MANAGE}),
    ),
    ("GET", "/api/v1/roles"): ("all", frozenset({PermissionCode.ROLE_READ})),
    ("GET", "/api/v1/audit-events"): ("all", frozenset({PermissionCode.AUDIT_READ})),
}


def _settings() -> Settings:
    return Settings(
        database_url=normalize_postgres_url(
            "postgresql://user:pass@ep-unit-pooler.neon.tech/unit"
        ),
        direct_database_url=normalize_postgres_url(
            "postgresql://user:pass@ep-unit.neon.tech/unit"
        ),
        jwt_secret_key="authorization-contract-secret-0001",
    )


def _api_routes() -> dict[Operation, APIRoute]:
    app = create_app(_settings())
    try:
        return {
            (method, route.path): route
            for route in app.routes
            if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
            for method in route.methods
        }
    finally:
        app.state.database.dispose()


def _permission_dependency(route: APIRoute) -> Callable[[User], User] | None:
    candidates = [
        dependency.call
        for dependency in route.dependant.dependencies
        if getattr(dependency.call, "__name__", "") == "dependency"
    ]
    assert len(candidates) <= 1, f"multiple permission dependencies on {route.path}"
    return candidates[0] if candidates else None


def _dependency_contract(dependency: Callable[[User], User]) -> Requirement:
    closure = dict(
        zip(dependency.__code__.co_freevars, dependency.__closure__ or (), strict=True)
    )
    wanted = frozenset(PermissionCode(code) for code in closure["wanted"].cell_contents)
    names = set(dependency.__code__.co_names)
    mode = "all" if "issubset" in names else "any" if "isdisjoint" in names else ""
    assert mode, "unknown permission dependency mode"
    return mode, wanted


def _user(role_name: UserRole) -> User:
    role_id = f"role-{role_name.value}"
    role = Role(
        id=role_id,
        name=role_name.value,
        description="authorization contract fixture",
        is_system=True,
    )
    mappings: list[RolePermission] = []
    for index, code in enumerate(sorted(ROLE_PERMISSIONS[role_name], key=str)):
        permission = Permission(
            id=f"permission-{index}-{role_name.value}",
            code=code.value,
            description="authorization contract fixture",
        )
        mappings.append(
            RolePermission(
                role_id=role_id,
                permission_id=permission.id,
                permission=permission,
            )
        )
    role.permissions = mappings
    return User(
        id=f"user-{role_name.value}",
        username=f"contract-{role_name.value}",
        password_hash="unused",
        role_id=role_id,
        assigned_role=role,
        is_active=True,
    )


def test_generated_endpoint_role_matrix_matches_permission_catalogue() -> None:
    """Fail when a route is added, omitted, or protected by the wrong permission."""

    routes = _api_routes()
    expected_operations = PUBLIC_OPERATIONS | IDENTITY_OPERATIONS | EXPECTED_PERMISSIONS.keys()
    assert routes.keys() == expected_operations

    for operation, route in routes.items():
        dependency = _permission_dependency(route)
        if operation in PUBLIC_OPERATIONS | IDENTITY_OPERATIONS:
            assert dependency is None
            continue

        assert dependency is not None
        requirement = _dependency_contract(dependency)
        assert requirement == EXPECTED_PERMISSIONS[operation]
        mode, wanted = requirement
        for role_name, granted in ROLE_PERMISSIONS.items():
            expected_status = (
                200
                if (wanted.issubset(granted) if mode == "all" else not wanted.isdisjoint(granted))
                else 403
            )
            try:
                dependency(_user(role_name))
            except HTTPException as exc:
                actual_status = exc.status_code
            else:
                actual_status = 200
            assert actual_status == expected_status, (operation, role_name)

