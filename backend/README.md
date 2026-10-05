# Backend

FastAPI runs locally and stores application/audit records in hosted Neon
PostgreSQL. Start it from the repository root after applying migrations:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

The API uses the pooled `DATABASE_URL`; Alembic and checks use the direct
`DIRECT_DATABASE_URL`. Both are required, TLS is mandatory, and schema
creation never occurs at application startup.

`GET /healthz` is process-only liveness. `GET /readyz` is a manual,
database-backed readiness check and should not be polled.

The service remains human-in-the-loop: every model output is decision support
only, and a qualified human records the final decision.
