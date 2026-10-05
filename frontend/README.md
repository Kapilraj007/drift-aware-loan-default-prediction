# Frontend

The React/Vite frontend runs locally and sends `/api` requests through the
Vite development proxy.

```powershell
Copy-Item .env.example .env.local
npm ci
npm run dev
```

The default API target is `http://127.0.0.1:8000`; override
`VITE_PROXY_TARGET` in `.env.local` if needed.

Quality commands:

```powershell
npm run lint
npm run test -- --run
npm run build
npm run preview
```

The product is decision support only. A qualified human makes the final
lending decision.
