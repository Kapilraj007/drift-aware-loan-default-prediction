# Drift-Aware Loan Default Decision Support

This local research showcase estimates loan-default risk, conditionally shows
model explanations, records a qualified human's decision, and monitors drift.
It never approves or declines a loan automatically.

```text
Browser -> Vite proxy -> FastAPI -> Neon pooled endpoint -> Neon PostgreSQL
                            |
                            +-> local model and Parquet artifacts

Alembic, seed, check, and export scripts -> Neon direct endpoint
Automated tests                          -> separate Neon test branch
```

See [Architecture](docs/architecture.md), [RBAC](docs/rbac.md), the
[full-stack contract](docs/full_stack_contract.md), and the
[showcase walkthrough](docs/showcase_walkthrough.md) for details.

## Prerequisites

- Python 3.12
- Node.js 22
- A free Neon account and internet access
- PowerShell 7 on Windows, or a POSIX-compatible shell on macOS/Linux

Application and audit records live in Neon. Feature stores, preprocessors, and
model bundles remain under the ignored local `data/` tree.

## One-time Neon setup

1. Create a Neon project in the region closest to the showcase machine.
2. In **Connect**, copy the main branch's pooled URL (host contains `-pooler`)
   as `DATABASE_URL` and direct URL as `DIRECT_DATABASE_URL`.
3. Create a child branch named `test`; copy its direct URL as
   `TEST_DATABASE_URL`. Never point tests at the showcase branch.
4. Copy `.env.example` to ignored `.env`. Fill the three URLs and a unique
   `JWT_SECRET_KEY` of at least 32 characters.
5. Keep `sslmode=require` and any supplied `channel_binding=require` option.

Never commit secrets. Rotate the Neon role password immediately if a URL is
exposed.

## First-time setup: one command

The setup wrapper creates the venv, installs dependencies, migrates and checks
Neon, trains the 20,000-row synthetic demo model, seeds four users, and runs
static checks. It stops on the first failure.

```powershell
.\scripts\dev-setup.ps1
```

```sh
./scripts/dev-setup.sh
```

On its first run, the wrapper creates `.env` and stops. Fill it, then run the
same command again. It also copies the non-secret frontend defaults to ignored
`frontend/.env.local` when that file is absent.

Manual equivalents:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Push-Location frontend
npm ci
Pop-Location
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\check_db.py --pooled
.\.venv\Scripts\python.exe scripts\prepare_demo.py
.\.venv\Scripts\python.exe scripts\export_openapi.py
Push-Location frontend
npm run generate:openapi
Pop-Location
```

`prepare_demo.py` generates synthetic LendingClub-shaped data, builds the
feature store, trains all three model families, writes sample application and
drift cohorts, verifies a real prediction, migrates Neon, and seeds demo data.

## Day-to-day start: one command

Run this one or two minutes before a demo; it checks and wakes Neon, then starts
the one-worker API and Vite frontend. Ctrl+C stops both. Logs are under
`.tmp/dev-logs/`.

```powershell
.\scripts\dev-start.ps1
```

```sh
./scripts/dev-start.sh
```

| Service | URL |
| --- | --- |
| Frontend | <http://127.0.0.1:5173> |
| API / OpenAPI | <http://127.0.0.1:8000> / <http://127.0.0.1:8000/docs> |
| DB-free liveness | <http://127.0.0.1:8000/healthz> |
| Manual readiness | <http://127.0.0.1:8000/readyz> |

Manual start, in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
Set-Location frontend
npm run dev -- --host 127.0.0.1
```

The Vite proxy is the only frontend proxy. `/readyz` reaches Neon and loads the
model, so use it manually and never poll it.

## Demo credentials

These development defaults come from `.env.example`; change them if the
showcase machine is shared. The UI shows them only when
`VITE_SHOW_DEMO_CREDENTIALS=true`.

| Role / arm | Username | Default password |
| --- | --- | --- |
| Administrator | `admin` | `Admin@Demo2026` |
| Risk analyst | `analyst` | `Analyst@Demo2026` |
| Officer, explanation | `officer.explain` | `Officer1@Demo2026` |
| Officer, score-only | `officer.scoreonly` | `Officer2@Demo2026` |

## Pre-demo checklist

1. Confirm internet access.
2. Run the start wrapper one or two minutes early to wake Neon.
3. Open `/readyz` once; confirm database, migration, and model readiness.
4. Confirm the synthetic-model banner is visible.
5. Log in once as all four demo users and check their sidebar entries.
6. Confirm both cohort CSVs exist in `samples/`.
7. Optionally export a read-only backup with
   `.\.venv\Scripts\python.exe scripts\export_demo_db.py --output backups\pre-show.json`.

## Database lifecycle and safety

- The API uses only the pooled `DATABASE_URL`.
- Alembic and administrative scripts use only the direct
  `DIRECT_DATABASE_URL`.
- Runtime connections use pre-ping, a small pool, a 240-second recycle,
  bounded cold-start retries, and `prepare_threshold=None` for PgBouncer.
- Startup stops with `alembic upgrade head` guidance if migrations are behind.
- `/healthz` never queries Neon; `/readyz` is a manual DB-backed diagnostic.
- Tests require a direct `TEST_DATABASE_URL` for a separate Neon branch. The
  guard rejects the configured showcase endpoints before destructive checks.
- The migration integration check performs `upgrade head -> downgrade base ->
  upgrade head`; never use the showcase URL as `TEST_DATABASE_URL`.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\pytest -p no:cacheprovider
Push-Location frontend
npm run lint
npm run test -- --run
npm run build
npm run test:e2e
Pop-Location
```

The plain Playwright command is safe to use for test discovery, but the
real-stack suite is deliberately skipped unless `E2E_REAL_STACK=true`.
For a real run, first migrate and seed a dedicated Neon test branch and start
the API and UI on ports 8000 and 5173 with the API connected to that branch.
Never use the showcase branch. In the Playwright terminal, provide the direct
test-branch URL and masked credentials explicitly:

```powershell
$env:TEST_DATABASE_URL = "postgresql://TEST_USER:***@ep-test.REGION.aws.neon.tech/TEST_DB?sslmode=require"
$env:E2E_REAL_STACK = "true"
$env:E2E_ADMIN_PASSWORD = "***"
$env:E2E_ANALYST_PASSWORD = "***"
$env:E2E_EXPLAIN_PASSWORD = "***"
$env:E2E_SCORE_ONLY_PASSWORD = "***"
npm --prefix frontend run test:e2e
```

`TEST_DATABASE_URL` must be the direct URL of the isolated test branch. The
suite refuses a pooled test URL and refuses a test target that matches an
exported showcase `DATABASE_URL` or `DIRECT_DATABASE_URL`. The test URL only
enables the safety guard; it does not reconfigure an already-running API, so
verify the API process itself was launched against the same isolated branch.
Consult the [verification report](docs/verification_report.md) before calling a
check passed; it separates executed evidence from unverified work.

## Troubleshooting

| Symptom | Meaning and action |
| --- | --- |
| Database waking / slow first request | Wait for the bounded retry, then run `scripts/check_db.py --pooled` once. |
| Connection timeout | Confirm internet access, Neon project state/quota, endpoint names, and password. |
| SSL or channel-binding error | Copy the URL again and retain `sslmode=require` and supplied channel binding. Never disable SSL. |
| `prepared statement ... does not exist` | Ensure runtime `DATABASE_URL` contains `-pooler`, keep auto-prepare disabled, and rerun `scripts/check_db.py --pooled`. |
| Alembic fails through a pooler | `DIRECT_DATABASE_URL` must use the non-`-pooler` endpoint. |
| Password was rotated | Replace both main-branch URLs in `.env`, then restart the API. |
| Free-plan quota exhausted | Check Neon usage and avoid polling DB-backed endpoints. |
| Migration behind | Run `.\.venv\Scripts\python.exe -m alembic upgrade head`, then restart. |
| Model missing | Run `.\.venv\Scripts\python.exe scripts\prepare_demo.py --artifacts-only`, then restart. |
| HTTP 422 | Request data is invalid; correct the returned field errors. This is not an infrastructure failure. |
| HTTP 503 | The model or database is unavailable. For `database_waking`, allow retry, then use `/readyz`. |
| Setup stops during seed | Check all four `SEED_*_PASSWORD` values, migration head, and that `APP_ENV` is not `production`. |

## Optional emergency backup

The read-only JSON exporter uses the direct endpoint. It supplements, but does
not replace, Neon branches or managed backups.

```powershell
.\.venv\Scripts\python.exe scripts\export_demo_db.py --output backups\demo-export.json
```

There is intentionally no automatic restore command. Restore into a newly
migrated Neon branch with a reviewed one-time importer so foreign-key ordering
and account data can be checked explicitly.

## Repository layout

```text
src/drift_loan/       data pipeline, training, drift harness, CLI
backend/app/          FastAPI routes, services, PostgreSQL models, seed logic
backend/migrations/   Alembic migrations (direct Neon endpoint)
frontend/             routed React/Vite/Ant Design application
scripts/              setup, start, check, preparation, and export tools
samples/              sample application and reference/drifted cohorts
tests/                unit and guarded Neon integration tests
docs/                 architecture, RBAC, walkthrough, contract, and evidence
data/                 local raw/interim/processed/model artifacts (ignored)
```

Synthetic results are demonstration evidence only and must not be presented as
research performance. Feature engineering, temporal splits, model selection,
thresholds, and published metrics are intentionally unchanged.
