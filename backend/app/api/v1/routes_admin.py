"""Administrative users, role catalogue, and audit-event APIs."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ...core.rbac import PermissionCode, UserRole
from ...core.security import hash_password, require_permissions
from ...db.session import get_session
from ...models.db_models import AuditEvent, Role, RolePermission, User
from ...models.schemas import (
    AuditEventListResponse,
    AuditEventResponse,
    ResetPasswordResponse,
    RoleResponse,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from ...services.audit_service import record_audit_event
from .routes_auth import user_response

users_router = APIRouter(prefix="/users", tags=["users"])
roles_router = APIRouter(prefix="/roles", tags=["roles"])
audit_router = APIRouter(prefix="/audit-events", tags=["audit"])


def _role(session: Session, name: UserRole) -> Role:
    role = session.scalar(select(Role).where(Role.name == name.value))
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RBAC catalogue is not seeded; run python -m backend.app.db.seed",
        )
    return role


def _user_options():
    return (
        selectinload(User.assigned_role)
        .selectinload(Role.permissions)
        .selectinload(RolePermission.permission)
    )


def _get_user(session: Session, user_id: str) -> User:
    user = session.scalar(select(User).options(_user_options()).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _protect_admin_change(
    session: Session,
    target: User,
    actor: User,
    *,
    new_role: Role | None,
    new_active: bool | None,
) -> None:
    if target.id == actor.id and new_active is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An administrator cannot deactivate their own account",
        )
    current_role = target.assigned_role.name if target.assigned_role is not None else ""
    demoting = new_role is not None and new_role.name != UserRole.ADMIN.value
    deactivating = new_active is False and target.is_active
    if (
        current_role != UserRole.ADMIN.value
        or not target.is_active
        or not (demoting or deactivating)
    ):
        return

    admin_role = session.scalar(
        select(Role).where(Role.name == UserRole.ADMIN.value).with_for_update()
    )
    assert admin_role is not None
    active_admins = int(
        session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role_id == admin_role.id, User.is_active.is_(True))
        )
        or 0
    )
    if active_admins <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The last active administrator cannot be deactivated or demoted",
        )


@users_router.get("", response_model=UserListResponse)
def list_users(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_permissions(PermissionCode.USER_MANAGE))],
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    role: UserRole | None = None,
    active: bool | None = None,
) -> UserListResponse:
    del current_user
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    statement = select(User).join(Role, User.role_id == Role.id)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                User.username.ilike(pattern),
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    if role is not None:
        statement = statement.where(Role.name == role.value)
    if active is not None:
        statement = statement.where(User.is_active.is_(active))
    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    users = session.scalars(
        statement.options(_user_options()).order_by(User.username).offset(offset).limit(limit)
    ).all()
    return UserListResponse(
        items=[user_response(user) for user in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@users_router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_permissions(PermissionCode.USER_MANAGE))],
) -> UserResponse:
    if session.scalar(select(User.id).where(User.username == payload.username)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if payload.email and session.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    role = _role(session, payload.role)
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role_id=role.id,
        email=payload.email,
        full_name=payload.full_name,
        must_change_password=payload.must_change_password,
        is_active=True,
    )
    session.add(user)
    session.flush()
    user.assigned_role = role
    record_audit_event(
        session,
        "user.created",
        actor=current_user,
        entity_type="user",
        entity_id=user.id,
        metadata={"role": role.name},
        request=request,
    )
    return user_response(user)


@users_router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_permissions(PermissionCode.USER_MANAGE))],
) -> UserResponse:
    del current_user
    return user_response(_get_user(session, user_id))


@users_router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_permissions(PermissionCode.USER_MANAGE))],
) -> UserResponse:
    target = _get_user(session, user_id)
    new_role = _role(session, payload.role) if payload.role is not None else None
    _protect_admin_change(
        session,
        target,
        current_user,
        new_role=new_role,
        new_active=payload.is_active,
    )
    if payload.email and session.scalar(
        select(User.id).where(User.email == payload.email, User.id != target.id)
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    changed: list[str] = []
    for field in ("full_name", "email", "is_active"):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            if getattr(target, field) != value:
                setattr(target, field, value)
                changed.append(field)
    if new_role is not None and target.role_id != new_role.id:
        target.role_id = new_role.id
        target.assigned_role = new_role
        changed.append("role")
        record_audit_event(
            session,
            "role.changed",
            actor=current_user,
            entity_type="user",
            entity_id=target.id,
            metadata={"role": new_role.name},
            request=request,
        )
    if "is_active" in changed and target.is_active is False:
        action = "user.deactivated"
    else:
        action = "user.updated"
    if changed:
        record_audit_event(
            session,
            action,
            actor=current_user,
            entity_type="user",
            entity_id=target.id,
            metadata={"fields": changed},
            request=request,
        )
    session.flush()
    return user_response(target)


@users_router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    user_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_permissions(PermissionCode.USER_MANAGE))],
) -> ResetPasswordResponse:
    target = _get_user(session, user_id)
    temporary_password = f"Aa1!{secrets.token_urlsafe(12)}"
    target.password_hash = hash_password(temporary_password)
    target.must_change_password = True
    target.failed_login_count = 0
    target.locked_until = None
    record_audit_event(
        session,
        "password.reset",
        actor=current_user,
        entity_type="user",
        entity_id=target.id,
        request=request,
    )
    session.flush()
    return ResetPasswordResponse(temporary_password=temporary_password)


@roles_router.get("", response_model=list[RoleResponse])
def list_roles(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_permissions(PermissionCode.ROLE_READ))],
) -> list[RoleResponse]:
    del current_user
    roles = session.scalars(
        select(Role).options(selectinload(Role.permissions).selectinload(RolePermission.permission))
    ).all()
    return [
        RoleResponse(
            id=role.id,
            name=UserRole(role.name),
            description=role.description,
            is_system=role.is_system,
            permissions=sorted(mapping.permission.code for mapping in role.permissions),
        )
        for role in sorted(roles, key=lambda item: item.name)
    ]


@audit_router.get("", response_model=AuditEventListResponse)
def list_audit_events(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_permissions(PermissionCode.AUDIT_READ))],
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    entity_type: str | None = None,
    actor_user_id: str | None = None,
    actor: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> AuditEventListResponse:
    del current_user
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    statement = select(AuditEvent, User.username.label("actor_username")).outerjoin(
        User, AuditEvent.actor_user_id == User.id
    )
    if action:
        statement = statement.where(AuditEvent.action == action)
    if entity_type:
        statement = statement.where(AuditEvent.entity_type == entity_type)
    if actor_user_id:
        statement = statement.where(AuditEvent.actor_user_id == actor_user_id)
    if actor:
        actor_value = actor.strip()
        statement = statement.where(
            or_(
                User.username.ilike(f"%{actor_value}%"),
                AuditEvent.actor_user_id == actor_value,
            )
        )
    if date_from:
        statement = statement.where(AuditEvent.created_at >= date_from)
    if date_to:
        statement = statement.where(AuditEvent.created_at <= date_to)
    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = session.execute(
        statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return AuditEventListResponse(
        items=[
            AuditEventResponse(
                id=event.id,
                actor_user_id=event.actor_user_id,
                actor_username=actor_username,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                metadata=event.event_metadata,
                ip=event.ip,
                created_at=event.created_at,
            )
            for event, actor_username in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
