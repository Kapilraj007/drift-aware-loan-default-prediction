"""JWT authentication and managed role creation routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.security import (
    UserRole,
    create_access_token,
    get_current_user,
    get_optional_current_user,
    get_settings_from_request,
    hash_password,
    verify_password,
)
from ...db.session import get_session
from ...models.db_models import User
from ...models.schemas import LoginRequest, TokenResponse, UserRegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


def _response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=UserRole(user.role),
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegisterRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> UserResponse:
    """Bootstrap the first admin, then permit only admins to create users."""

    existing_count = int(session.scalar(select(func.count()).select_from(User)) or 0)
    if existing_count and (current_user is None or current_user.role != UserRole.ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can create additional users",
        )
    if session.scalar(select(User).where(User.username == payload.username)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    role = UserRole.ADMIN.value if existing_count == 0 else payload.role.value
    user = User(username=payload.username, password_hash=hash_password(payload.password), role=role)
    session.add(user)
    session.flush()
    return _response(user)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> TokenResponse:
    user = session.scalar(select(User).where(User.username == payload.username))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=create_access_token(user, settings),
        expires_in_seconds=settings.access_token_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
def current_identity(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return _response(current_user)
