"""JWT login, identity, and password-change routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.rbac import UserRole
from ...core.security import (
    create_access_token,
    get_current_user,
    get_settings_from_request,
    hash_password,
    permission_codes,
    user_role_name,
    verify_and_update_password,
    verify_password,
)
from ...db.session import get_session
from ...models.db_models import User
from ...models.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
)
from ...services.audit_service import record_audit_event

router = APIRouter(prefix="/auth", tags=["authentication"])
_LOGIN_ERROR = "Incorrect username or password"


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=UserRole(user_role_name(user)),
        permissions=sorted(permission_codes(user)),
        email=user.email,
        full_name=user.full_name,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _login_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_LOGIN_ERROR,
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> TokenResponse:
    now = datetime.now(UTC)
    user = session.scalar(select(User).where(User.username == payload.username).with_for_update())
    locked = user is not None and user.locked_until is not None and user.locked_until > now
    valid = (
        user is not None
        and user.is_active
        and not locked
        and verify_password(payload.password, user.password_hash)
    )
    if not valid:
        newly_locked = False
        if user is not None and user.is_active and not locked:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                newly_locked = True
        record_audit_event(
            session,
            "login.failure",
            actor_user_id=user.id if user is not None else None,
            entity_type="user" if user is not None else None,
            entity_id=user.id if user is not None else None,
            metadata={"locked": bool(locked or newly_locked)},
            request=request,
        )
        session.commit()
        raise _login_error()

    assert user is not None
    verified, replacement_hash = verify_and_update_password(payload.password, user.password_hash)
    if not verified:
        raise _login_error()
    if replacement_hash is not None:
        user.password_hash = replacement_hash
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    record_audit_event(
        session,
        "login.success",
        actor=user,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    session.flush()
    return TokenResponse(
        access_token=create_access_token(user, settings),
        expires_in_seconds=settings.access_token_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
def current_identity(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return user_response(current_user)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if verify_password(payload.new_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password",
        )
    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    record_audit_event(
        session,
        "password.changed",
        actor=current_user,
        entity_type="user",
        entity_id=current_user.id,
        request=request,
    )
    session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
