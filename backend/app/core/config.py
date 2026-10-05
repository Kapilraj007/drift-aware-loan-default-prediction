"""Environment-backed settings for a local API using hosted Neon PostgreSQL."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _dotenv() -> dict[str, str]:
    """Read the local ignored .env without mutating process environment."""

    path = Path(".env")
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "").isalnum():
            continue
        values[name] = value.strip().strip("'").strip('"')
    return values


def _environment() -> dict[str, str]:
    values = _dotenv()
    values.update(os.environ)
    return values


def _required(values: dict[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise ValueError(
            f"{name} is required. Copy .env.example to .env and add the Neon "
            "connection string from the Connect dialog."
        )
    return value


def _integer(values: dict[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    value = values.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed


def _origins(values: dict[str, str]) -> tuple[str, ...]:
    origins = (origin.strip() for origin in values.get("CORS_ORIGINS", "").split(","))
    return tuple(dict.fromkeys(origin for origin in origins if origin))


def normalize_postgres_url(value: str, *, name: str = "database URL") -> str:
    """Return a psycopg SQLAlchemy URL with mandatory encrypted transport."""

    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"postgresql", "postgres", "postgresql+psycopg"}:
        raise ValueError(f"{name} must use postgresql:// or postgresql+psycopg://")
    if not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError(f"{name} must include a host and database name")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    sslmode = query.get("sslmode")
    if sslmode == "disable":
        raise ValueError(f"{name} must not use sslmode=disable")
    if sslmode is None:
        query["sslmode"] = "require"
    return urlunsplit(
        ("postgresql+psycopg", parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def database_target(value: str) -> tuple[str, str]:
    """Return a credential-free host/database identity for safety comparisons."""

    parsed = urlsplit(normalize_postgres_url(value))
    return (parsed.hostname or "", parsed.path.strip("/"))


def mask_database_url(value: str) -> str:
    """Mask credentials and the unique Neon endpoint prefix for safe diagnostics."""

    parsed = urlsplit(normalize_postgres_url(value))
    host = parsed.hostname or "unknown-host"
    labels = host.split(".")
    masked_host = "ep-***." + ".".join(labels[1:]) if host.startswith("ep-") else "***"
    user = parsed.username or "unknown-user"
    port = f":{parsed.port}" if parsed.port else ""
    database = parsed.path.strip("/") or "unknown-database"
    return f"postgresql+psycopg://{user}:***@{masked_host}{port}/{database}"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings. Both runtime and administrative URLs are mandatory."""

    database_url: str
    direct_database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    model_artifact_directory: Path = Path("data/artifacts/model")
    preprocessor_artifact_directory: Path = Path("data/artifacts/preprocessor")
    prediction_threshold: float = 0.50
    cors_origins: tuple[str, ...] = ()
    db_pool_size: int = 3
    db_max_overflow: int = 2
    db_pool_recycle_seconds: int = 240
    db_connect_timeout_seconds: int = 15
    db_connect_retries: int = 5
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    drift_rehydrate_limit: int = 1_000
    web_concurrency: int = 1
    log_level: str = "INFO"
    app_env: str = "development"

    def __post_init__(self) -> None:
        if len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters")

    @classmethod
    def from_environment(cls) -> Settings:
        values = _environment()
        threshold_text = values.get("PREDICTION_THRESHOLD", "0.50")
        try:
            threshold = float(threshold_text)
        except ValueError as exc:
            raise ValueError("PREDICTION_THRESHOLD must be a number") from exc
        if not 0.0 < threshold < 1.0:
            raise ValueError("PREDICTION_THRESHOLD must be strictly between 0 and 1")

        database_url = normalize_postgres_url(
            _required(values, "DATABASE_URL"), name="DATABASE_URL"
        )
        direct_database_url = normalize_postgres_url(
            _required(values, "DIRECT_DATABASE_URL"), name="DIRECT_DATABASE_URL"
        )
        runtime_host, _ = database_target(database_url)
        direct_host, _ = database_target(direct_database_url)
        if "-pooler" not in runtime_host:
            warnings.warn(
                "DATABASE_URL should use Neon's pooled endpoint (host contains '-pooler').",
                stacklevel=2,
            )
        if "-pooler" in direct_host:
            warnings.warn(
                "DIRECT_DATABASE_URL should use Neon's direct endpoint (no '-pooler').",
                stacklevel=2,
            )

        pool_recycle = _integer(values, "DB_POOL_RECYCLE_SECONDS", 240)
        if pool_recycle >= 300:
            raise ValueError(
                "DB_POOL_RECYCLE_SECONDS must be below Neon's five-minute idle "
                "suspend window (use 240)."
            )

        jwt_secret_key = _required(values, "JWT_SECRET_KEY")
        if len(jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters")

        return cls(
            database_url=database_url,
            direct_database_url=direct_database_url,
            jwt_secret_key=jwt_secret_key,
            jwt_algorithm=values.get("JWT_ALGORITHM", "HS256"),
            access_token_minutes=_integer(values, "ACCESS_TOKEN_MINUTES", 30),
            model_artifact_directory=Path(
                values.get("MODEL_ARTIFACT_DIRECTORY", "data/artifacts/model")
            ),
            preprocessor_artifact_directory=Path(
                values.get("PREPROCESSOR_ARTIFACT_DIRECTORY", "data/artifacts/preprocessor")
            ),
            prediction_threshold=threshold,
            cors_origins=_origins(values),
            db_pool_size=_integer(values, "DB_POOL_SIZE", 3),
            db_max_overflow=_integer(values, "DB_MAX_OVERFLOW", 2, minimum=0),
            db_pool_recycle_seconds=pool_recycle,
            db_connect_timeout_seconds=_integer(
                values, "DB_CONNECT_TIMEOUT_SECONDS", 15
            ),
            db_connect_retries=_integer(values, "DB_CONNECT_RETRIES", 5),
            login_max_failures=_integer(values, "LOGIN_MAX_FAILURES", 5),
            login_lock_minutes=_integer(values, "LOGIN_LOCK_MINUTES", 15),
            drift_rehydrate_limit=_integer(values, "DRIFT_REHYDRATE_LIMIT", 1_000),
            web_concurrency=_integer(values, "WEB_CONCURRENCY", 1),
            log_level=values.get("LOG_LEVEL", "INFO").upper(),
            app_env=values.get("APP_ENV", "development"),
        )


def direct_database_url_from_environment() -> str:
    """Return only the direct URL for migration and administrative scripts."""

    values = _environment()
    return normalize_postgres_url(
        _required(values, "DIRECT_DATABASE_URL"), name="DIRECT_DATABASE_URL"
    )


def runtime_database_url_from_environment() -> str:
    """Return only the pooled URL for connectivity checks."""

    values = _environment()
    return normalize_postgres_url(_required(values, "DATABASE_URL"), name="DATABASE_URL")


def optional_environment_value(name: str) -> str | None:
    """Read a process-or-dotenv value without exposing any other settings."""

    value = _environment().get(name, "").strip()
    return value or None
