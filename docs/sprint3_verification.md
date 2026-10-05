# Local frontend verification

> The former static-server and multi-service verification path was removed in
> Phase 2. Vite is the only supported frontend proxy.

With FastAPI on port 8000 and Vite on port 5173:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8000/readyz
cd frontend
npm run lint
npm run test -- --run
npm run build
```

Manually verify login, application persistence, scoring, explanation-arm
behavior, human feedback, monitoring, and retraining review. The exact Phase
0–3 command evidence is maintained in `docs/verification_report.md`.
