# Loan Review Console

The Sprint 3 React interface supports the human-reviewed flow:

- sign in with the existing JWT API and role-aware navigation;
- enter one application manually or load its first CSV/JSON row, validate it,
  persist it, and request a risk score;
- view a risk card plus an accessible signed, top-five SHAP explanation when
  assigned to the explanation study arm;
- record approve, decline, or escalate feedback with agreement/override and a
  note; and
- for analysts and admins, inspect recorded KS/ADWIN monitoring history, run
  a cohort comparison, and open a human-gated retraining review ticket.

The UI never makes an automated lending decision. The backend records the
officer's study assignment, the explanation exposure, detector state, feedback
state, and review ticket. Retraining is never queued or deployed by the UI.

## Local development

From this directory, install dependencies and start the Vite development
server. Its `/api` proxy targets `http://127.0.0.1:8000` by default.

```powershell
npm ci
npm run dev
```

Set `VITE_PROXY_TARGET` to use a different API address, or set
`VITE_API_BASE_URL` when deploying the static bundle behind another proxy.
The API must allow the development origin through `CORS_ORIGINS` when it is
not accessed through the same-origin Nginx proxy.

## Checks

```powershell
npm run lint
npm run test
npm run build
```

The tests cover data quality and file parsing, typed API error handling,
application-to-prediction sequencing, SHAP visibility, officer feedback,
monitoring rendering, and the human confirmation required for a retraining
review ticket.

## Container service

The multistage `Dockerfile` builds the static UI and serves it with Nginx. It
proxies `/api` to the Compose `api` service and supports SPA routes. Start the
profile after configuring the main Compose environment:

```powershell
docker compose --profile frontend up --build frontend
```
