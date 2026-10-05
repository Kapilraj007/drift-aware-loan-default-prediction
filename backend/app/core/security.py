"""Argon2 password hashing, JWT identity, and permission dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..db.session import get_session
from ..models.db_models import Role, RolePermission, User
from .config import Settings
from .rbac import PermissionCode

_LEGACY_PASSWORD_SCHEME = "pbkdf2_sha256"
_LEGACY_PASSWORD_ITERATIONS = 310_000
_PASSWORD_HASH = PasswordHash.recommended()
_bearer_scheme = HTTPBearer(auto_error=False)


def validate_password_policy(password: str) -> str:
    """Validate the server-side password policy and return the password."""

    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters")
    if len(password) > 256:
        raise ValueError("Password must contain at most 256 characters")
    if not any(character.isalpha() for character in password):
        raise ValueError("Password must contain at least one letter")
    if not any(character.isdigit() for character in password):
        raise ValueError("Password must contain at least one digit")
    return password


def hash_password(password: str) -> str:
    """Create an Argon2id password hash after enforcing the policy."""

    return _PASSWORD_HASH.hash(validate_password_policy(password))


def legacy_hash_password(password: str) -> str:
    """Create the retired PBKDF2 representation for migration tests only."""

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _LEGACY_PASSWORD_ITERATIONS
    )

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return (
        f"{_LEGACY_PASSWORD_SCHEME}${_LEGACY_PASSWORD_ITERATIONS}${encode(salt)}${encode(digest)}"
    )


def _verify_legacy_password(password: str, encoded: str) -> bool:
    try:
        scheme, iteration_text, encoded_salt, encoded_digest = encoded.split("$", 3)
        if scheme != _LEGACY_PASSWORD_SCHEME:
            return False
        iterations = int(iteration_text)
        salt = base64.urlsafe_b64decode(encoded_salt + "=" * (-len(encoded_salt) % 4))
        expected = base64.urlsafe_b64decode(encoded_digest + "=" * (-len(encoded_digest) % 4))
    except (TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def verify_and_update_password(password: str, encoded: str) -> tuple[bool, str | None]:
    """Verify any supported hash and return an Argon2id replacement when needed."""

    if encoded.startswith(f"{_LEGACY_PASSWORD_SCHEME}$"):
        valid = _verify_legacy_password(password, encoded)
        return valid, hash_password(password) if valid else None
    try:
        return _PASSWORD_HASH.verify_and_update(password, encoded)
    except (TypeError, ValueError):
        return False, None


def verify_password(password: str, encoded: str) -> bool:
    """Compatibility wrapper for callers that do not need transparent rehashing."""

    return verify_and_update_password(password, encoded)[0]


def create_access_token(user: User, settings: Settings) -> str:
    """Issue a short-lived token containing identity, never mutable permissions."""

    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "username": user.username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_settings_from_request(request: Request) -> Settings:
    try:
        return request.app.state.settings
    except AttributeError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI application settings were not initialized") from exc


def _user_statement(user_id: str):
    return (
        select(User)
        .options(
            joinedload(User.assigned_role)
            .joinedload(Role.permissions)
            .joinedload(RolePermission.permission)
        )
        .where(User.id == user_id)
    )


def load_user_with_permissions(session: Session, user_id: str) -> User | None:
    """Load the current database role and permission rows in one request query."""

    return session.execute(_user_statement(user_id)).unique().scalar_one_or_none()


def user_role_name(user: User) -> str:
    if user.assigned_role is None:
        raise RuntimeError("User has no assigned role; run the RBAC seed")
    return user.assigned_role.name


def permission_codes(user: User) -> frozenset[str]:
    if user.assigned_role is None:
        return frozenset()
    return frozenset(
        mapping.permission.code
        for mapping in user.assigned_role.permissions
        if mapping.permission is not None
    )


def has_permission(user: User, permission: PermissionCode | str) -> bool:
    return str(permission) in permission_codes(user)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> User:
    """Resolve an active user and re-read permissions on every request."""

    if credentials is None:
        raise _credentials_error()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
    except jwt.PyJWTError as exc:
        raise _credentials_error() from exc
    if not isinstance(user_id, str):
        raise _credentials_error()

    user = load_user_with_permissions(session, user_id)
    if user is None or not user.is_active or user.assigned_role is None:
        raise _credentials_error()
    return user


def require_permissions(*required: PermissionCode | str):
    """Require every supplied permission code."""

    wanted = frozenset(str(permission) for permission in required)

    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if not wanted.issubset(permission_codes(current_user)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return dependency


def require_any_permission(*required: PermissionCode | str):
    """Require at least one supplied permission code."""

    wanted = frozenset(str(permission) for permission in required)

    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if wanted.isdisjoint(permission_codes(current_user)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return dependency
