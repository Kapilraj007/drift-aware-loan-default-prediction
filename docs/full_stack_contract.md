# Full-stack contract matrix

This is the Phase 8 map from visible UI behavior to the versioned API. Paths
below are relative to `/api/v1`. The API is authoritative: hiding a control is
not an authorization boundary. Ownership checks still apply to `*_read_own`.

The evidence column names the check that must stay green. A final result is
recorded only in `docs/verification_report.md`; this matrix is not itself a
claim that a live-stack check passed.

## UI calls

| UI feature | Method and endpoint | Required permission | Evidence |
| --- | --- | --- | --- |
| Login | `POST /auth/login` | public; active, unlocked account | backend auth tests; Playwright four-role login |
| Restore session / user menu | `GET /auth/me` | authenticated | backend identity test; auth-context test |
| Change password | `POST /auth/change-password` | authenticated | backend password test; profile UI test |
| Wizard field definitions | `GET /reference/application-schema` | `application:create` | schema contract test; wizard test |
| Create application | `POST /applications` | `application:create` | backend API test; officer E2E |
| Applications table | `GET /applications` | `application:read_own` or `application:read_all` | pagination/ownership API test; officer E2E |
| Application header/detail | `GET /applications/{id}` | own/all read plus ownership | cross-owner 403 test |
| Complete review view | `GET /applications/{id}/review` | own/all application and prediction read | both-arm masking API test; review-page test |
| Score an application | `POST /predictions` | `prediction:create` | real-bundle integration test; officer E2E |
| Prediction detail | `GET /predictions/{id}` | `prediction:read_own` or `prediction:read_all` | ownership and masking API tests |
| Record or amend decision | `POST /feedback` | `feedback:create` plus ownership | decision history API test; officer E2E |
| Explanation arm | `GET /experiments/explanation-assignment` | `experiment:participate` | assignment test |
| Explanation exposure | `POST /experiments/explanation-exposures` | `experiment:participate` plus ownership | idempotency/masking test; review-page test |
| Dashboard | `GET /dashboard/summary` | `dashboard:read` | own/all aggregation test; role E2E |
| Study results | `GET /experiments/summary` | `experiment:read_results` | aggregate API test; study-page test |
| Drift status chip/page | `GET /monitoring/status` | `monitoring:read` | monitoring API test; analyst E2E |
| Drift trend | `GET /monitoring/history` | `monitoring:read` | restart-persistence test |
| KS check | `POST /monitoring/feature-drift` | `monitoring:run_check` | sample-cohort API test; analyst E2E |
| Ticket table | `GET /retraining-tickets` | `retraining:read` | retraining API test |
| Open ticket | `POST /retraining-tickets` | `retraining:create` | drift prerequisite test; analyst E2E |
| Review ticket | `POST /retraining-tickets/{id}/review` | `retraining:review` | admin-only API test; admin E2E |
| Model card | `GET /model` | `model:read` | model API test; model-page test |
| Training metadata | `GET /training-runs` | `model:read` | model API test |
| User table | `GET /users` | `user:manage` | pagination/RBAC API test; admin E2E |
| Create user | `POST /users` | `user:manage` | validation/audit API test; admin E2E |
| Edit/deactivate user | `PATCH /users/{id}` | `user:manage` | last-admin/deactivation tests; admin E2E |
| Reset password | `POST /users/{id}/reset-password` | `user:manage` | one-time-value/audit test; users-page test |
| Permission matrix | `GET /roles` | `role:read` | seeded-catalogue API test; roles-page test |
| Audit table | `GET /audit-events` | `audit:read` | filter/pagination API test; audit-page test |

## Backend endpoints without a direct page call

| Endpoint | Reason retained |
| --- | --- |
| `GET /feedback` | Administrative/API audit access and contract compatibility; the application-review aggregate supplies the page timeline. |
| `GET /predictions` | Paginated API access and contract compatibility; the applications/review pages are the primary UI. |
| `GET /users/{id}` | Stable detail endpoint for integrations; the admin table currently edits from its loaded row. |
| `GET /healthz` | External process liveness. It is deliberately DB-free and never polled by the UI. |
| `GET /readyz` | Manual pre-demo diagnostic only; UI polling would wake Neon and consume quota. |
| `GET /openapi.json`, `/docs` | Generated developer contract and interactive API documentation. |

## Contract-generation and review checks

1. Export OpenAPI from `create_app()` and diff it against every path used by
   `frontend/src/api/client.ts`.
2. Generate or validate TypeScript API shapes from that OpenAPI document; a
   hand-maintained type must not silently diverge.
3. Run the generated endpoint-by-role test for all three roles and ownership
   variants.
4. Run Playwright against the real seeded stack for both officer arms, analyst,
   and admin.
5. Record exact commands, output, skips, and live-environment limitations in
   `docs/verification_report.md`.
