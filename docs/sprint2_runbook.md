# Local API runbook

> The former multi-service topology was removed in Phase 2. This runbook now
> describes the supported local application plus hosted Neon workflow.

1. Confirm internet access and populate the three Neon URLs in the ignored
   `.env`.
2. Wake and check the database:

   ```powershell
   .\.venv\Scripts\python.exe scripts\check_db.py --pooled
   ```

3. Apply schema changes through the direct endpoint:

   ```powershell
   .\.venv\Scripts\python.exe -m alembic upgrade head
   ```

4. Start the API:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
   ```

5. Start `npm run dev` in `frontend/`.

Use `/healthz` for liveness without waking Neon. Use `/readyz` manually
when checking database, migration, and model readiness.
