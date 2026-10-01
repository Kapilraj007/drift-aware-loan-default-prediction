# Drift Aware Loan Default Prediction

This repository contains the completed Sprint 1 and Sprint 2 foundation plus
the Sprint 3 React review console for a drift-aware, explainable loan-default
research system. It turns
LendingClub-shaped accepted-loan CSV files into a leakage-safe,
time-partitioned Parquet feature store, trains and evaluates chronological
default-risk models, and exposes auditable decision-support APIs, a
role-aware human-review interface, and drift monitoring.

The system is decision support for human credit officers. It does not approve
or decline applications, and its trained artifacts are research models rather
than a production lending-decision system.

## Documentation guide

- [`data/README.md`](data/README.md) explains dataset acquisition, target
  construction, the chronological train/validation/test split, preprocessing,
  feature views, model families, and the verified evaluation results.
- [`docs/sprint1_data_flow.md`](docs/sprint1_data_flow.md) documents the feature
  pipeline and leakage controls in detail.
- [`docs/sprint2_runbook.md`](docs/sprint2_runbook.md) covers model training and
  local API operations.
- [`frontend/README.md`](frontend/README.md) covers the reviewer interface.
- [`docs/sprint3_verification.md`](docs/sprint3_verification.md) is the complete
  local verification and smoke-test runbook.

## Sprint 1 result

- Strict CSV ingestion with an explicit predictor allowlist and documented
  post-origination leakage denylist.
- Binary outcome construction: `Charged Off` and `Default` map to `1`, `Fully
  Paid` maps to `0`, and unresolved statuses are excluded and counted.
- Shared `LoanFeatureTransformer` used by both the training pipeline and the
  future FastAPI service through `backend/app/ml/transform_features.py`.
- Median imputation learned only from the temporal training window, a missing
  flag for every numeric and engineered feature, fixed target-independent
  grade/sub-grade mappings, and training-only one-hot vocabularies.
- Engineered loan-to-income, installment-to-income, and credit-history-years
  features.
- Both unscaled tree-model features and a StandardScaler view for the Sprint 2
  logistic-regression baseline.
- Deterministic, complete-quarter train/validation/shift splits and Parquet
  partitions by `issue_quarter`.
- Persisted transformer, schema, scaler metadata, build manifest, and a
  run-specific data dictionary with observed null rates.
- Reproducible time-window slicing plus seeded absolute/relative perturbations
  for `int_rate` and `dti`, with an audit manifest and before/after statistics.
- Executable EDA notebook for resolved-loan class balance, quarterly volume,
  and quarterly default rate.
- Dataset provenance, citation, licensing caveats, static schema documentation,
  pinned dependencies, Docker packaging, and automated tests.

## Sprint 2 result

- LightGBM primary model, XGBoost robustness cross-check, and L2 logistic
  baseline trained from the existing frozen Parquet feature store.
- Expanding-window temporal model selection, with thresholds selected on
  validation only and a locked latest-quarter shift evaluation.
- Versioned estimator, feature schema, metrics, persisted SHAP TreeExplainer,
  and ADWIN detector under `data/artifacts/model/`.
- FastAPI backend with JWT roles, applications, predictions, SHAP narratives,
  feedback audit logging, KS feature drift, and ADWIN score-stream status.
- PostgreSQL, Redis, API, and opt-in Celery worker Docker Compose topology.

## Sprint 3 result

- React/Vite loan-review interface with JWT sign-in, role-aware navigation,
  accessible loading/error states, and a responsive desktop/mobile layout.
- Manual and first-row CSV/JSON application intake, client-side data-quality
  checks, persisted application-to-prediction sequencing, and a risk-score
  card that remains decision support rather than an automated loan decision.
- Server-recorded loan-officer explanation-study assignment: the
  explanation arm receives an accessible signed top-five SHAP view and
  narrative, while the score-only arm is protected by the API as well as the
  UI.
- Auditable approve, decline, and escalate feedback with agreement/override
  state and notes; analyst/admin KS and ADWIN monitoring history; and a
  human-confirmed retraining-review ticket that never queues or deploys a
  model automatically.
- Production static frontend container with an Nginx same-origin `/api` proxy,
  available through the opt-in `frontend` Docker Compose profile.

See the [Sprint 3 verification runbook](docs/sprint3_verification.md) for the
local quality checks, live smoke flow, and isolated inference load test.

The primary LightGBM run achieved validation ROC-AUC **0.7188**, PR-AUC
**0.3904**, F1 **0.4412**, and held-out shift ROC-AUC **0.6948**, PR-AUC
**0.3817**, F1 **0.4418**. These are decision-support metrics, not an
automated approval/denial policy. The late 2018 labels have maturity limitations,
so interpret per-quarter results alongside aggregate metrics. See the
[Sprint 2 completion report](docs/sprint2_completion_report.md) and
[operations runbook](docs/sprint2_runbook.md).

## Verified real-data run

Sprint 1 has been executed against Kaggle's Version 3 LendingClub accepted-loan
artifact, not only against synthetic fixtures. The preserved archive is
`accepted_2007_to_2018Q4.csv.gz` (392,582,231 bytes; SHA-256
`55c16f75120f897683f02e7aabcf080d0e4a20c4832feb1d592cfa941bd62a2d`).
The decompressed pipeline input is 1,675,133,810 bytes with SHA-256
`3eae03c28fd9d2e8a076ebeb73507e8d4d0f44d90500decdb0936e0933d1f36a`.

The completed run produced:

- 2,260,701 accepted-loan rows scanned;
- 1,345,350 resolved outcomes: 1,076,751 fully paid and 268,599
  default/charged-off loans;
- 47 chronological partitions from 2007Q2 through 2018Q4;
- 53 leakage-safe model features;
- 274,970 training, 726,519 validation, and 343,861 shift rows; and
- zero missing/non-finite model values and an empty leakage-feature
  intersection in the persisted feature store.

The machine-readable evidence is in
[`data/raw/acquisition_manifest.csv`](data/raw/acquisition_manifest.csv), the
local feature-store `manifest.json`, and
`reports/generated/feature_store_validation.json`. Generated row-level and
report artifacts remain excluded from version control.

The plan's default secondary benchmark, UCI Statlog German Credit, is also
downloaded from the official UCI archive and checksum-verified. Its 1,000 rows
are staged for later cross-dataset model evaluation and are not combined with
the LendingClub feature store.

## Data flow

```text
Accepted-loan CSV
  -> allowlisted ingestion and outcome resolution
  -> complete-quarter temporal split
  -> fit transformer on train only
  -> transform validation and shift with frozen state
  -> unscaled + scaled Parquet partitions by issue quarter
  -> arbitrary time windows
  -> optional seeded interest-rate / DTI perturbation
```

The verified feature store uses complete, non-overlapping issue quarters:

| Dataset role | Issue quarters | Rows | Purpose |
| --- | --- | ---: | --- |
| Train | 2007Q2-2014Q1 | 274,970 | Fit preprocessing and estimators |
| Validation | 2014Q2-2016Q2 | 726,519 | Select model settings and thresholds |
| Test / shift holdout | 2016Q3-2018Q4 | 343,861 | Final locked temporal evaluation |

The trained model families are LightGBM (primary), XGBoost (robustness
cross-check), and L2 logistic regression (scaled-feature baseline). See the
[data and modeling README](data/README.md) for the split rules, why the latest
window is called `shift` in code, and per-model validation/test metrics.

See [the detailed data flow](docs/sprint1_data_flow.md), [the data
dictionary](docs/data_dictionary.md), and [the provenance and redistribution
policy](docs/data_provenance.md). The measured results and gate evidence are in
the [Sprint 1 completion report](docs/sprint1_completion_report.md).

## Local setup

Python 3.11 through 3.13 is supported. The commands below use PowerShell.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Raw and derived row-level data are intentionally ignored by Git.

## Fast end-to-end smoke run

The demo generator creates LendingClub-shaped synthetic rows solely for
pipeline verification. Do not use its outputs as research findings.

```powershell
& .\.venv\Scripts\python.exe scripts\generate_demo_data.py `
  --output data\raw\demo_accepted_loans.csv --rows 400

& .\.venv\Scripts\python.exe -m drift_loan build `
  --input data\raw\demo_accepted_loans.csv `
  --feature-store data\processed\demo_feature_store `
  --artifact-directory data\artifacts\demo_preprocessor `
  --overwrite

& .\.venv\Scripts\python.exe -m drift_loan simulate-drift `
  data\processed\demo_feature_store `
  --int-rate-shift 0.15 --int-rate-mode relative `
  --dti-shift 3 --dti-mode absolute `
  --seed 20260926 `
  --output data\processed\demo_drift_window.parquet
```

Every build prints a JSON summary. The feature-store manifest records source
paths, loaded columns, unresolved-row counts, split quarters, row counts,
feature order, seed, and fitted-artifact location. Every simulated window gets
an adjacent `.manifest.json` audit record.

## Reproduce the research-data run

The current local workspace already contains the verified archive and extracted
input. For a new environment, review `docs/data_provenance.md`, acquire the
accepted-loan file through Kaggle's official workflow, fill
`data/raw/acquisition_manifest.csv`, and place the extracted file at
`data/raw/accepted_loans.csv`. Then run:

```powershell
& .\.venv\Scripts\python.exe -m drift_loan build `
  --config config\pipeline.json `
  --overwrite

& .\.venv\Scripts\python.exe scripts\validate_feature_store.py `
  data\processed\feature_store `
  --acquisition-manifest data\raw\acquisition_manifest.csv `
  --output reports\generated\feature_store_validation.json

& .\.venv\Scripts\python.exe scripts\validate_acquisitions.py `
  data\raw\acquisition_manifest.csv `
  --output reports\generated\acquisition_validation.json
```

The pipeline accepts multiple `--input` arguments, tolerates the common Kaggle
preamble before the CSV header, and automatically selects a disk-backed,
bounded-memory build for large inputs. `--chunk-size` controls its parser and
transform batches. It refuses to overwrite a feature store unless
`--overwrite` is explicit.

## Execute the EDA notebook

```powershell
& .\.venv\Scripts\python.exe scripts\execute_eda_notebook.py `
  --data data\raw\accepted_loans.csv `
  --output-notebook reports\generated\01_eda_executed.ipynb `
  --output-dir reports\generated\eda
```

The runner hashes the configured input and writes only aggregate tables,
figures, metadata, and the executed notebook. The source notebook contains no
cached or fabricated findings.

## Train and serve the Sprint 2 system

Train all three model families from the existing feature store. The command
writes the primary LightGBM artifact, SHAP explainer, ADWIN state, schema, and
validation/shift metrics atomically.

```powershell
& .\.venv\Scripts\python.exe -m drift_loan train-model `
  --feature-store data\processed\feature_store `
  --model-directory data\artifacts\model `
  --overwrite

& .\.venv\Scripts\python.exe scripts\evaluate_sprint2_model.py `
  --feature-store data\processed\feature_store `
  --model-directory data\artifacts\model `
  --output reports\generated\sprint2_model_evaluation.json
```

For local API, database, Redis, and optional queue-worker startup, follow the
[Sprint 2 runbook](docs/sprint2_runbook.md). The API Swagger UI is available at
`/docs` after startup.

## Run the Sprint 3 interface

With the API available locally, start the Vite development server from the
frontend directory. Its `/api` proxy targets `http://127.0.0.1:8000` by
default.

```powershell
Push-Location frontend
npm ci
npm run dev
Pop-Location
```

Set `VITE_PROXY_TARGET` for a different development API address, or
`VITE_API_BASE_URL` when serving the static bundle behind another proxy. See
the [frontend README](frontend/README.md) for the supported flow and roles.

## Docker

```powershell
docker build -t drift-loan-sprint1:verified .
docker run --rm --mount "type=bind,source=${PWD},target=/project" `
  drift-loan-sprint1:verified build `
  --input /project/data/raw/accepted_loans.csv `
  --feature-store /project/data/processed/feature_store `
  --artifact-directory /project/data/artifacts/preprocessor
```

The container defaults to the `drift-loan` CLI and uses pinned runtime
dependencies. The image has been built and launched successfully, including
containerized feature-store and drift-simulation smoke runs; exact evidence is
in `reports/generated/docker_validation.json`. Notebook execution and tests use
`requirements-dev.txt` locally.

The Sprint 3 static frontend is an opt-in Compose profile so it does not alter
the API-only workflow. It builds `frontend/Dockerfile`, serves the SPA with
Nginx, and proxies `/api` to the Compose API service:

```powershell
docker compose --profile frontend up --build frontend
```

It is available at `http://localhost:5173` by default; set `FRONTEND_PORT` to
change the host port.

## Quality checks

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

The Python coverage threshold is an independent required gate: report the
test-case result and coverage-gate result separately if the assertions pass
but coverage remains below 85%.

## Repository layout

```text
backend/       FastAPI application, persistence, auth, inference, and monitoring services
config/        Reproducible pipeline configuration
data/          Raw, interim, processed, and fitted-artifact locations
docs/          Data dictionary, source registry, provenance, and architecture
frontend/      Sprint 3 React/Vite loan-review interface, tests, and Nginx container
monitoring/    Drift-harness boundary and monitor workspace
notebooks/     Data-aware Sprint 1 EDA
scripts/       Demo generation, notebook execution, validation, and reproducibility
src/           Installable data-pipeline and drift-simulation package
tests/         Unit, integration, CLI, and notebook-contract tests
```
