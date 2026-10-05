"""Hard guards preventing database tests from targeting showcase data."""

from __future__ import annotations

from sqlalchemy.engine import make_url

from ..core.config import (
    database_target,
    normalize_postgres_url,
    optional_environment_value,
)


class UnsafeTestDatabaseError(RuntimeError):
    """Raised before any test-side connection is opened."""


def require_test_database_url() -> str:
    test_value = optional_environment_value("TEST_DATABASE_URL")
    if test_value is None:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL is not configured; database tests require the direct "
            "URL of a dedicated Neon test branch."
        )
    test_url = normalize_postgres_url(test_value, name="TEST_DATABASE_URL")
    test_target = database_target(test_url)
    if "-pooler" in test_target[0]:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL must be a direct Neon endpoint, not a pooled endpoint."
        )

    for name in ("DATABASE_URL", "DIRECT_DATABASE_URL"):
        value = optional_environment_value(name)
        if value is None:
            continue
        configured = normalize_postgres_url(value, name=name)
        # A Neon child branch normally retains the same database name, so the
        # safe identity is endpoint host + database rather than database alone.
        if test_target == database_target(configured):
            raise UnsafeTestDatabaseError(
                f"Refusing database tests: TEST_DATABASE_URL targets the same "
                f"endpoint and database as {name}."
            )
    return test_url


def pooled_url_for_test_branch(direct_url: str) -> str:
    """Derive Neon's pooled hostname for the same isolated test branch."""

    parsed = make_url(normalize_postgres_url(direct_url))
    host = parsed.host or ""
    if "-pooler" not in host:
        first, separator, rest = host.partition(".")
        host = f"{first}-pooler{separator}{rest}"
    return parsed.set(host=host).render_as_string(hide_password=False)
