"""Password hashing, JWT issuing, and role-based FastAPI dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..models.db_models import User
from .config import Settings


class UserRole(StrEnum):
    """Roles supported by the decision-support API."""

    LOAN_OFFICER = "loan_officer"
    RISK_ANALYST = "risk_analyst"
    ADMIN = "admin"


_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 310_000
_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Return a salted PBKDF2-SHA256 password record.

    PBKDF2 uses only the Python standard library, making bootstrap and local
    test environments independent of a database-side extension or a running
    password service.
    """

    if not password:
        raise ValueError("Password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    def encode(value):
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"{_PASSWORD_SCHEME}${_PASSWORD_ITERATIONS}${encode(salt)}${encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a PBKDF2 password record without leaking timing information."""

    try:
        scheme, iteration_text, encoded_salt, encoded_digest = encoded.split("$", 3)
        if scheme != _PASSWORD_SCHEME:
            return False
        iterations = int(iteration_text)
        padding = "=" * (-len(encoded_salt) % 4)
        salt = base64.urlsafe_b64decode(encoded_salt + padding)
        padding = "=" * (-len(encoded_digest) % 4)
        expected = base64.urlsafe_b64decode(encoded_digest + padding)
    except (TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_access_token(user: User, settings: Settings) -> str:
    """Issue a short-lived signed token containing the immutable user identity."""

    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
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
    # Kept as a small dependency instead of a global so app factories can use
    # isolated SQLite databases and secrets in tests.
    try:
        return request.app.state.settings
    except AttributeError as exc:  # pragma: no cover - protects misconfigured embedding apps
        raise RuntimeError("FastAPI application settings were not initialized") from exc


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> User:
    """Resolve an active database user from a bearer token."""

    if credentials is None:
        raise _credentials_error()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        token_role = payload.get("role")
    except jwt.PyJWTError as exc:
        raise _credentials_error() from exc
    if not isinstance(user_id, str) or not isinstance(token_role, str):
        raise _credentials_error()

    user = session.get(User, user_id)
    if user is None or not user.is_active or user.role != token_role:
        raise _credentials_error()
    return user


def get_optional_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> User | None:
    """Return no user for an absent header, but reject an invalid supplied token."""

    if credentials is None:
        return None
    return get_current_user(credentials, session, settings)


def require_roles(*roles: UserRole):
    """Return a dependency that permits one or more named roles."""

    allowed = frozenset(role.value for role in roles)

    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role is not permitted to perform this action",
            )
        return current_user

    return dependency
