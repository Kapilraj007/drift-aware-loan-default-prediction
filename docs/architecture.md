# Architecture

This showcase is a local web application backed by hosted Neon PostgreSQL.
Only application and audit records leave the machine; feature-store Parquet
files, preprocessors, and trained model artifacts stay under the ignored
`data/` tree.

```text
                            local showcase machine

  Browser
     |
     | http://127.0.0.1:5173/api/*
     v
  Vite dev/preview proxy  ------------------------------+
     |                                                   |
     | http://127.0.0.1:8000/api/v1/*                    |
     v                                                   |
  FastAPI (one worker)                                   |
     |               \                                   |
     |                +--> data/artifacts/model          |
     |                +--> data/artifacts/preprocessor   |
     |                                                   |
     | DATABASE_URL: pooled, TLS, prepare disabled       |
     v                                                   |
  Neon pooled endpoint --> Neon PostgreSQL <-------------+
                               ^
                               |
             DIRECT_DATABASE_URL: direct, TLS
                               |
              Alembic / seed / check / export scripts
```

## Connection responsibilities

| Component | URL | Why |
| --- | --- | --- |
| FastAPI request traffic | `DATABASE_URL` (host contains `-pooler`) | PgBouncer multiplexes the small runtime pool. Psycopg automatic prepare is disabled for transaction pooling. |
| Alembic | `DIRECT_DATABASE_URL` | Migrations need a direct session and are never run through PgBouncer. |
| Seed, connectivity check, optional export | `DIRECT_DATABASE_URL` | Administrative scripts use predictable session behavior and print only masked targets. |
| Automated tests | `TEST_DATABASE_URL` | A direct URL for a separate Neon branch; guards reject showcase targets before connecting. |

TLS is mandatory. URL normalization adds `sslmode=require` when missing and
refuses `sslmode=disable`; a supplied `channel_binding=require` is preserved.

## Runtime lifecycle

1. FastAPI retries the first database connection with bounded backoff so a
   suspended Neon compute can wake.
2. Startup compares the database's Alembic revision with repository `head` and
   stops with an actionable migration command when they differ.
3. `/healthz` reports process liveness without any database query.
4. `/readyz` is a manual diagnostic for database latency, migration state, and
   model loading. The frontend never polls it.
5. Prediction scores and aggregate monitoring snapshots are persisted. A
   restart rehydrates the single-process ADWIN/KS view from that history.

The showcase intentionally runs one API worker. The in-memory detector is
rehydrated, but it is not a distributed streaming system; multiple workers
would maintain independent live detector instances and therefore trigger a
startup warning.

## Trust and safety boundaries

- A score is decision support, never an automatic approval or decline.
- Explanation-study assignment is enforced by the API. A score-only officer
  never receives contributor data in any response.
- Permissions are loaded from PostgreSQL on authenticated requests so role
  changes and deactivation take effect immediately.
- Audit events contain actor/action/entity metadata only. Passwords, tokens,
  connection strings, and raw applicant features are excluded.
- Applicant cohorts used for KS checks are processed in memory; only aggregate
  detector results are persisted.

## Quota-aware behavior

Neon Free-plan compute may suspend while idle. The frontend uses cached,
user-triggered refreshes rather than background polling, and liveness checks do
not touch the database. Before a demo, run `scripts/check_db.py --pooled` once
to wake compute and validate both connection paths.
