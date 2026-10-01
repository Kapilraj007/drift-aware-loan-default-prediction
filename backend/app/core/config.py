"""Environment-backed backend settings.

The backend deliberately keeps configuration small and explicit so that local
SQLite tests, a Docker deployment, and a managed database use the same app
factory.  No connection is opened while this module is imported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _integer_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _origins_env(name: str) -> tuple[str, ...]:
    """Return a de-duplicated comma-separated origin allowlist."""

    values = (origin.strip() for origin in os.getenv(name, "").split(","))
    return tuple(dict.fromkeys(origin for origin in values if origin))


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings, with safe local defaults for development and tests."""

    database_url: str = "sqlite:///./data/loan_backend.db"
    jwt_secret_key: str = "change-this-development-secret-before-deployment"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    model_artifact_directory: Path = Path("data/artifacts/model")
    preprocessor_artifact_directory: Path = Path("data/artifacts/preprocessor")
    prediction_threshold: float = 0.50
    cors_origins: tuple[str, ...] = ()
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None

    @classmethod
    def from_environment(cls) -> Settings:
        defaults = cls()
        threshold_text = os.getenv("PREDICTION_THRESHOLD", "0.50")
        try:
            threshold = float(threshold_text)
        except ValueError as exc:
            raise ValueError("PREDICTION_THRESHOLD must be a number") from exc
        if not 0.0 < threshold < 1.0:
            raise ValueError("PREDICTION_THRESHOLD must be strictly between 0 and 1")

        return cls(
            database_url=os.getenv("DATABASE_URL", defaults.database_url),
            jwt_secret_key=os.getenv("JWT_SECRET_KEY", defaults.jwt_secret_key),
            jwt_algorithm=os.getenv("JWT_ALGORITHM", defaults.jwt_algorithm),
            access_token_minutes=_integer_env("ACCESS_TOKEN_MINUTES", 60),
            model_artifact_directory=Path(
                os.getenv("MODEL_ARTIFACT_DIRECTORY", "data/artifacts/model")
            ),
            preprocessor_artifact_directory=Path(
                os.getenv("PREPROCESSOR_ARTIFACT_DIRECTORY", "data/artifacts/preprocessor")
            ),
            prediction_threshold=threshold,
            cors_origins=_origins_env("CORS_ORIGINS"),
            bootstrap_admin_username=os.getenv("BOOTSTRAP_ADMIN_USERNAME") or None,
            bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or None,
        )
