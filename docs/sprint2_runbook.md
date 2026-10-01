# Sprint 2 local operations runbook

This runbook defines the local API, optional training-worker, PostgreSQL, and
Redis topology. It is for reproducible research and decision support, not an
automated credit-approval system.

## Architecture

```text
Client
  -> FastAPI API (port 8000) -> PostgreSQL: users, applications, predictions, feedback/audit records
                             -> Redis: optional isolated batch-work queue
                             -> /models/current (read-only model artifact)

Redis/Celery optional worker -> /data/feature_store (read-only)
                              -> /models/current (write model + metadata atomically)
                              -> /reports (write evaluation reports)
```

`docker-compose.yml` runs the API from `backend.app.main:app` and the worker
from `python -m backend.app.worker`. The application image must therefore
include the backend package and its FastAPI, database, Redis, and worker
dependencies. Compose overrides the existing Sprint 1 CLI entrypoint only for
these two services.

The feature store bind mount is read-only in both application services. The
worker is the only service with write access to the configured model-artifact
directory. The fitted preprocessor is mounted read-only at
`/models/preprocessor`. Store a versioned estimator, model metadata, the fitted
preprocessor reference or copy, feature-order hash, training-data hash, split
boundaries, selected validation threshold, and evaluation metrics together.
The API must load a complete version atomically and treat a missing or invalid
artifact as *not ready*, rather than silently using a fallback model.

## Before starting

1. Install Docker Desktop with Docker Compose v2 and make sure it is running.
2. Build the real feature store first, or use the existing verified store at
   `data/processed/feature_store`. The worker expects it at
   `/data/feature_store` inside the container.
3. Copy the example environment file and replace every placeholder secret.
   Keep the real `.env` local and use a secrets manager outside local
   development. Set the optional bootstrap-admin credentials before the first
   startup if you want the service to create the initial local administrator.

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force data\artifacts\model, reports\generated
docker compose config
```

Use URL-safe passwords in `.env`; otherwise URL-encode them before they are
inserted into the database and Redis URLs. Do not expose PostgreSQL or Redis
ports to the host: use `docker compose exec` for local troubleshooting.

## Build and start

```powershell
docker compose build
docker compose up -d
docker compose ps
docker compose logs --follow api
```

The queue worker is an explicit operational profile so ordinary API startup
does not depend on queued training being enabled. Start it only when background
batch scoring, drift recomputation, or a queue-backed training integration is
configured:

```powershell
docker compose --profile queue up -d worker
docker compose logs --follow worker
```

Check liveness, readiness, and the generated OpenAPI contract. Liveness may
pass before a model is trained; readiness must fail until a valid model
artifact is available.

```powershell
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
Invoke-RestMethod http://localhost:8000/openapi.json
```

Authenticate before calling a protected model, application, prediction,
feedback, or monitoring route. The command below keeps the password out of
PowerShell history; enter the same local bootstrap username and password that
you configured in `.env`.

```powershell
$credential = Get-Credential -UserName local-admin -Message "Local API login"
$plainPassword = $credential.GetNetworkCredential().Password
$loginBody = @{ username = $credential.UserName; password = $plainPassword } | ConvertTo-Json
$login = Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/api/v1/auth/login `
  -ContentType "application/json" `
  -Body $loginBody
Remove-Variable plainPassword
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/me -Headers $headers
```

The bootstrap credentials are used only when the database is empty. For a
fresh database without bootstrap variables, `POST /api/v1/auth/register` can
create the first admin; after that, only an admin can register more users.

If startup fails, first inspect the service logs. Database and Redis have
health checks, so an API that never starts normally indicates an invalid
environment value, missing application dependency, or incorrect image build.

```powershell
docker compose logs postgres redis api
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select 1"'
docker compose exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" ping'
```

Those commands read credentials inside the containers rather than placing a
password in shell history.

## Train and inspect a model

The guaranteed reproducible local training path is the CLI below. It fits only
on the stored `train` split, selects the model/threshold using `validation`,
and writes the locked final-shift evaluation and model metadata next to the
serialized artifact. Do not train by calling the prediction endpoint or by
letting the API process fit a model.

```powershell
& .\.venv\Scripts\python.exe -m drift_loan train-model `
  --feature-store data\processed\feature_store `
  --model-directory data\artifacts\model `
  --overwrite
```

The equivalent command through the Compose worker image uses the container
mounts, so its paths are deliberately different:

```powershell
docker compose --profile queue run --rm --no-deps --entrypoint python worker `
  -m drift_loan train-model `
  --feature-store /data/feature_store `
  --model-directory /models/current `
  --overwrite
```

Retain the model version, artifact checksum, selected threshold, feature-order
hash, split metadata, and evaluation report produced by either command. The
canonical model metadata endpoint is `GET /api/v1/model`; it should report
these values without returning the serialized estimator.

The model directory is a single deployment unit: retain `metadata.json`,
`feature_schema.json`, `metrics.json`, `adwin_detector.joblib`,
`shap_explainer.joblib`, and every persisted estimator together. The model
loader verifies the primary-model and feature-schema hashes before serving; the
SHAP artifact and its integrity metadata must travel with the same version. A
lazy compatible-explainer fallback is acceptable only when the optional
explainer cannot load, and it must return an explicit unavailable explanation
without altering the model score.

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/v1/model -Headers $headers
Invoke-RestMethod -Uri http://localhost:8000/api/v1/training-runs -Headers $headers
```

The PostgreSQL/Redis worker topology is kept for operationally safe background
batch scoring, drift recomputation, and future queued training. The `worker`
service is behind the `queue` Compose profile, but it can still be used for the
one-off CLI command above. `GET /api/v1/training-runs` exposes recorded
artifact metadata. If a deployment later enables
`POST /api/v1/training-runs`, treat it as an optional queue submission interface
and verify its exact request/response schema in `/openapi.json` before
automation. It must enqueue work for the worker rather than executing model
fitting in the API process.

## Test inference and the service contract

Use only the documented origination-time fields. The example assumes an
authenticated development session; obtain a token through the service's
configured authentication flow and keep it out of scripts and source control.

```powershell
$application = @{
  annual_inc = 65000
  dti = 16.2
  revol_util = 42.1
  revol_bal = 12000
  open_acc = 9
  total_acc = 22
  delinq_2yrs = 0
  inq_last_6mths = 1
  loan_amnt = 12000
  term = "36 months"
  int_rate = 13.5
  installment = 407.3
  grade = "C"
  sub_grade = "C3"
  purpose = "debt_consolidation"
  emp_length = "5 years"
  home_ownership = "RENT"
  earliest_cr_line = "Jan-2006"
  issue_d = "Jan-2019"
}
$predictionRequest = @{ features = $application } | ConvertTo-Json -Depth 4

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/api/v1/predictions `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $predictionRequest
```

The response should include a probability, the persisted decision threshold,
model version, and an audit identifier. It must reject missing required fields,
non-finite values, and inputs that do not satisfy the shared feature-transform
contract. A probability is not a reason code or an approval/decline decision.

Run the automated checks after a model or API change:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m ruff check .
docker compose config
```

## Evaluation rules

The existing feature store is chronological and must remain so:

| Split | Issue quarters | Rows | Defaults | Default rate |
| --- | --- | ---: | ---: | ---: |
| Train | 2007Q2-2014Q1 | 274,970 | 43,089 | 15.6704% |
| Validation | 2014Q2-2016Q2 | 726,519 | 147,961 | 20.3657% |
| Final shift holdout | 2016Q3-2018Q4 | 343,861 | 77,549 | 22.5524% |

Fit the transformer and estimator only on train. Select algorithms,
calibration, and a decision threshold only on validation. Evaluate the locked
choice once on shift and do not feed shift metrics back into selection. Report
at least ROC-AUC, PR-AUC, Brier/calibration, precision, recall, F1, confusion
matrix, prevalence, and results by quarter; plain accuracy is misleading at
this class imbalance.

The reproducible Logistic Regression baseline trained on the scaled training
view achieved validation ROC-AUC 0.7158, PR-AUC 0.3862, and Brier score 0.1510.
At a 0.50 threshold it had 79.75% accuracy but only 1.74% recall; a validation
F1 search over 0.01 increments selected 0.15 (precision 34.53%, recall 60.41%,
F1 43.94%). Treat that threshold as a baseline result, not a universal credit
policy.

## Safety and data limitations

- This is research decision support. Keep a qualified human responsible for
  any credit decision; never automatically approve or decline a person from a
  score.
- Keep post-origination fields out of both training and prediction. The
  allowlist intentionally excludes payments, recoveries, balances after
  origination, later FICO values, hardship, and settlement fields.
- `grade`, `sub_grade`, and `int_rate` are allowed by the current project
  contract because they are treated as origination-time terms. They are not
  suitable for a pre-offer application score unless the availability contract
  is changed and the model is retrained/evaluated accordingly.
- Do not mix the UCI German Credit benchmark with LendingClub training data:
  it has a different schema and outcome definition.
- The late LendingClub labels are not equally mature. Default rates in the
  shift window fall from 25.96% in 2016Q3 to 9.87% in 2018Q3 and 2.43%
  (122 of 5,030 resolved loans) in 2018Q4. This is label-maturity/censoring
  evidence, so aggregate final-holdout metrics must be supplemented with
  quarter-level metrics and cannot support a current-deployment claim.
- Do not log raw application records, tokens, passwords, or model artifacts
  into public logs. Restrict CORS and rotate secrets outside local development.

## Stop and clean up

```powershell
docker compose down
```

This preserves the named PostgreSQL and Redis volumes and the host-mounted
model artifacts. To intentionally remove the local database/cache volumes,
first verify that the target project is `drift-loan`, then run
`docker compose down --volumes`. That does not remove host-mounted models or
reports; remove those only after retaining the artifacts required for audit and
reproducibility.
