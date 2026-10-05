"""Export the FastAPI OpenAPI contract without starting the database lifespan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "openapi.json",
    )
    args = parser.parse_args()
    # Contract export is deliberately offline and environment-independent.
    settings = Settings(
        database_url=(
            "postgresql+psycopg://contract:contract@ep-contract-pooler.example.invalid/"
            "contract?sslmode=require"
        ),
        direct_database_url=(
            "postgresql+psycopg://contract:contract@ep-contract.example.invalid/"
            "contract?sslmode=require"
        ),
        jwt_secret_key="offline-contract-export-secret-at-least-32-characters",
    )
    document = create_app(settings).openapi()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote OpenAPI {document['info']['version']} to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
