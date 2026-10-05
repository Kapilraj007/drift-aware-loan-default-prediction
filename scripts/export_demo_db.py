"""Export application tables to a portable JSON emergency backup.

This optional command is deliberately read-only and uses DIRECT_DATABASE_URL.
It is not a replacement for Neon branching or managed backups.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, select

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.core.config import (  # noqa: E402
    direct_database_url_from_environment,
    mask_database_url,
)

TABLE_ORDER = (
    "roles",
    "permissions",
    "role_permissions",
    "users",
    "applications",
    "predictions",
    "feedback",
    "explanation_experiment_assignments",
    "explanation_experiment_exposures",
    "monitoring_snapshots",
    "retraining_tickets",
    "audit_events",
)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def export_database(output: Path) -> dict[str, Any]:
    url = direct_database_url_from_environment()
    print(f"Reading via direct endpoint: {mask_database_url(url)}")
    engine = create_engine(url, future=True, pool_pre_ping=True)
    metadata = MetaData()
    metadata.reflect(bind=engine, only=list(TABLE_ORDER))
    exported: dict[str, list[dict[str, Any]]] = {}
    with engine.connect() as connection:
        for name in TABLE_ORDER:
            table = metadata.tables.get(name)
            if table is None:
                exported[name] = []
                continue
            rows = connection.execute(select(table)).mappings()
            exported[name] = [
                {key: _json_value(value) for key, value in row.items()} for row in rows
            ]
    engine.dispose()
    payload = {
        "format": "drift-loan-demo-export-v1",
        "exported_at": datetime.now().astimezone().isoformat(),
        "tables": exported,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote optional emergency backup to {output.resolve()}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("backups/demo-export.json"))
    args = parser.parse_args()
    export_database(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
