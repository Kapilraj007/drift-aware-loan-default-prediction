#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PYTHON=.venv/bin/python
if [ ! -x "$PYTHON" ]; then
  echo "Virtual environment not found. Run ./scripts/dev-setup.sh first." >&2
  exit 1
fi

"$PYTHON" scripts/check_db.py --pooled
mkdir -p .tmp/dev-logs

"$PYTHON" -m uvicorn backend.app.main:create_app --factory \
  --host 127.0.0.1 --port 8000 --workers 1 \
  >.tmp/dev-logs/api.stdout.log 2>.tmp/dev-logs/api.stderr.log &
API_PID=$!
(cd frontend && npm run dev -- --host 127.0.0.1) \
  >.tmp/dev-logs/frontend.stdout.log 2>.tmp/dev-logs/frontend.stderr.log &
WEB_PID=$!

cleanup() {
  kill "$API_PID" "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "API:      http://127.0.0.1:8000"
echo "Frontend: http://127.0.0.1:5173"
echo "Logs:     $ROOT/.tmp/dev-logs"
wait "$API_PID" "$WEB_PID"
