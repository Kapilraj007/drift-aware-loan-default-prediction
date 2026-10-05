"""Check and wake Neon using masked, TLS-only connection diagnostics."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.core.config import (  # noqa: E402
    direct_database_url_from_environment,
    mask_database_url,
    runtime_database_url_from_environment,
)
from backend.app.db.session import migration_is_current  # noqa: E402


def _probe(url: str, *, pooled: bool) -> bool:
    label = "pooled runtime" if pooled else "direct administrative"
    print(f"Connecting to {label} endpoint: {mask_database_url(url)}")
    connect_args: dict[str, object] = {"connect_timeout": 15}
    if pooled:
        connect_args["prepare_threshold"] = None
    engine = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    started = time.perf_counter()
    migration_current = True
    try:
        with engine.connect() as connection:
            server_version = connection.scalar(text("SHOW server_version"))
            database = connection.scalar(text("SELECT current_database()"))
            role = connection.scalar(text("SELECT current_user"))
            driver_connection = connection.connection.driver_connection
            ssl_in_use = bool(driver_connection.pgconn.ssl_in_use)
            generated_uuid = connection.scalar(text("SELECT gen_random_uuid()"))
            if pooled:
                for _ in range(25):
                    connection.execute(text("SELECT 1")).scalar_one()
                print("Prepared-statement safety probe: 25 repeated queries passed")
            else:
                current, actual, expected = migration_is_current(engine)
                migration_current = current
                actual_text = actual or "none"
                print(
                    f"Alembic revision: {actual_text}; expected: {expected}; "
                    f"state: {'current' if current else 'behind'}"
                )
                if not current:
                    print("Run 'alembic upgrade head' before starting the API.")
            elapsed_ms = (time.perf_counter() - started) * 1_000
            print(f"Connection time: {elapsed_ms:.1f} ms (includes any cold start)")
            print(f"Server: PostgreSQL {server_version}")
            print(
                f"Database: {database}; role: {role}; "
                f"client TLS: {'in use' if ssl_in_use else 'not in use'}"
            )
            print(f"gen_random_uuid(): {'available' if generated_uuid else 'unavailable'}")
            return bool(ssl_in_use and generated_uuid and migration_current)
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pooled",
        action="store_true",
        help="also probe the runtime pooler with 25 repeated queries",
    )
    args = parser.parse_args()
    try:
        direct_ready = _probe(direct_database_url_from_environment(), pooled=False)
        pooled_ready = True
        if args.pooled:
            pooled_ready = _probe(runtime_database_url_from_environment(), pooled=True)
        if not (direct_ready and pooled_ready):
            return 1
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Database check failed: {type(exc).__name__}.", file=sys.stderr)
        print(
            "Confirm internet access, the two Neon URLs, sslmode=require, and "
            "whether the compute quota is available.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
