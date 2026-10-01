# Backend Sprint 2 operations

The backend uses the shared, leakage-safe feature transformation contract in
`backend/app/ml`. Its local runtime topology is documented in
[`../docs/sprint2_runbook.md`](../docs/sprint2_runbook.md): FastAPI serves the
API, PostgreSQL persists application/job/model metadata, Redis carries training
jobs, and a separate worker performs model training.

For local startup, copy `.env.example` to `.env`, replace all placeholder
secrets, then use `docker compose build` and `docker compose up -d`. The API
expects a model-artifact mount at `/models/current`, while the worker is the
only application service allowed to write it. The feature store is mounted
read-only at `/data/feature_store`.

See the runbook for the training, health, readiness, prediction, evaluation,
and shutdown commands. It also documents the chronological split rule and the
late-label-maturity caveat that must accompany any model evaluation.
