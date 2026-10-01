# Sprint 3 verification and inference load test

This runbook verifies the React officer interface alongside the existing API.
Run it against a local or explicitly isolated test environment only. The
Locust scenario creates prediction/audit records and advances the API's
in-memory drift detector; it is not safe for production or shared research
data.

## Prerequisites

- Install the repository development dependencies, including the pinned Locust
  version in `requirements-dev.txt`.
- Configure `.env` with non-placeholder local secrets and use an isolated
  database/Compose project for load testing.
- Ensure the model, shared preprocessor, and feature-store mounts are present.
- Create a dedicated active `loan_officer` test user. Do not use a human or
  administrator account for load testing.
- The browser frontend must either use a same-origin `/api` Nginx proxy or the
  API must enable CORS for the frontend origin. A static frontend served from a
  separate origin cannot call the API otherwise.

Install the development tools in the project virtual environment before running
the checks or Locust:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pip install -e .
```

## Automated quality checks

From the repository root, run the same checks enforced by CI:

```powershell
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m pytest -q `
  --cov=drift_loan --cov-report=term-missing --cov-fail-under=85

Push-Location frontend
npm ci
npm run lint
npm run test
npm run build
Pop-Location
```

`npm run test` is the maintained Vitest command and already runs in
non-watch mode. CI may append `-- --run` for explicitness. There is no separate
browser-test script at present; use the live smoke flow below after the API is
available. The maintained frontend tests cover form/file validation,
browser-autofilled login submission, typed API failures,
application-to-prediction sequencing, durable study-arm visibility, signed
SHAP rendering, officer feedback, monitoring rendering, and the human
confirmation required for a retraining-review ticket.

The Python coverage threshold is a separate required gate. Record test-case
counts, the coverage percentage/gate result, and frontend test results
separately: a run whose assertions all pass still fails this quality check when
coverage is below 85%.

## Live Compose smoke test

Build and start the API topology, then verify its probes before starting the
browser or load test:

```powershell
docker compose build
docker compose up -d
docker compose ps
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
```

The included static frontend service is intentionally profile-gated so it does
not change the established API-only workflow. It builds `frontend/Dockerfile`,
serves the SPA through Nginx on port 80, and proxies same-origin `/api` calls
to the Compose API service. Start it with:

```powershell
docker compose --profile frontend up -d --build frontend
Invoke-WebRequest http://localhost:5173
```

It is exposed at `http://localhost:5173` by default; set `FRONTEND_PORT` to
override that host port. Confirm the complete browser flow before treating the
service as ready:

1. Sign in as an isolated `loan_officer`; submit valid manual input, then a
   first-row CSV or JSON file; check data-quality failures without submitting
   them; persist a valid application; and request its score.
2. Confirm the officer's server-assigned study arm: the explanation arm shows
   exactly the signed top-five SHAP contributors and records exposure, while
   the score-only arm never receives those contributors from the API.
3. Submit approve, decline, or escalate feedback with agreement/override and
   notes. Confirm the saved audit state after a refresh.
4. Sign in as an isolated `risk_analyst` or `admin`; inspect KS/ADWIN history,
   run an isolated cohort comparison that produces a drift state, and create a
   retraining review ticket only after explicit human confirmation. Confirm no
   model is queued or deployed by this action.
5. Verify that a loan officer receives a role-denied response for monitoring
   and retraining routes, and that the configured frontend origin passes the
   API CORS preflight when it is not using the Nginx proxy.

## Locust inference test

The scenario in `scripts/locustfile.py` authenticates each virtual user and
repeatedly sends the full direct-prediction feature contract. It validates a
201 response, a numeric score in `[0, 1]`, and a boolean risk flag. It tests
the actual inference and explanation path, not a mocked API.

Start with a small local run. Capture the password through PowerShell rather
than placing it in a command line or source file:

```powershell
$credential = Get-Credential -Message "Dedicated load-test loan-officer account"
$env:LOAD_TEST_USERNAME = $credential.UserName
$env:LOAD_TEST_PASSWORD = $credential.GetNetworkCredential().Password
$env:LOAD_TEST_BASE_URL = "http://localhost:8000"
New-Item -ItemType Directory -Force reports\generated\locust | Out-Null

& .\.venv\Scripts\locust.exe -f scripts\locustfile.py `
  --headless -u 5 -r 1 -t 1m --only-summary `
  --csv reports\generated\locust\inference `
  --html reports\generated\locust\inference.html

Remove-Variable credential
Remove-Item Env:\LOAD_TEST_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:\LOAD_TEST_USERNAME -ErrorAction SilentlyContinue
Remove-Item Env:\LOAD_TEST_BASE_URL -ErrorAction SilentlyContinue
```

Review the `POST /api/v1/predictions` row rather than the one-time login row:
there must be no failures, and latency/throughput must meet the agreed target
for the test environment. Increase users and spawn rate only after the small
run is clean. Stop the local stack with `docker compose down` when finished;
do not remove volumes unless their exact test scope has been verified.
