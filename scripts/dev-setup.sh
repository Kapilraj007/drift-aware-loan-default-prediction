#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Add the Neon URLs and a 32+ character JWT secret, then rerun." >&2
  exit 1
fi
if [ ! -f frontend/.env.local ]; then
  cp frontend/.env.example frontend/.env.local
fi

if [ ! -x .venv/bin/python ]; then
  python3.12 -m venv .venv
fi
PYTHON=.venv/bin/python

"$PYTHON" -m pip install -r requirements-dev.txt
"$PYTHON" -m pip install --no-deps -e .
(cd frontend && npm ci)
"$PYTHON" -m alembic upgrade head
"$PYTHON" scripts/check_db.py --pooled
"$PYTHON" scripts/prepare_demo.py
"$PYTHON" scripts/export_openapi.py
(cd frontend && npm run generate:openapi)
"$PYTHON" -m ruff check .
(cd frontend && npm run lint && npm run test -- --run && npm run build)

echo "Setup complete. Start with ./scripts/dev-start.sh"
