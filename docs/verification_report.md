# Verification report

This report separates implementation evidence from environment-dependent
verification. Connection strings, tokens, and passwords are never recorded.
Times below are observations from the commands that were actually run; they
are not performance targets.

## Current outcome

Phases 4 through 9 are implemented in the repository. Static checks, the
database-free backend suite, frontend unit tests, and the production frontend
build pass. The real-stack gate is not complete because the configured
showcase database is one migration behind, no separate TEST_DATABASE_URL is
configured, and authorization was not given to mutate the live showcase
database. Consequently, this report does not claim that live migrations,
seeding, four-role login, or Playwright E2E passed.

## Phase-by-phase implementation record

### Phases 1-3 - foundation carried forward

The local FastAPI plus Vite plus Neon architecture, guarded database
configuration, PostgreSQL-native models, Alembic, DB-free health check, and
direct/pooled connection checker remain in place. The latest read-only Neon
check found PostgreSQL 16.15 over TLS and a healthy pooled repeated-query
probe, but it also found the showcase schema at revision
0002_rbac_audit_schema rather than expected head
0003_rbac_feedback_history.

### Phase 4 - RBAC, authentication, and seed

Implemented table-driven roles and permissions, ownership checks, dynamic
permission loading, the four seeded demo identities, explicit study-arm
assignment, Argon2id with legacy PBKDF2 rehash, lockout, password policy,
admin safety rules, users/roles/audit APIs, and audit actor filtering.

Evidence includes the generated endpoint-by-role authorization contract test
and unit tests for seed guards and authentication behavior. The fresh-Neon
branch gate remains unverified because TEST_DATABASE_URL is absent.

### Phase 5 - backend review and contract

Implemented strict application validation with field-level 422 responses,
schema discovery, paginated read APIs and aggregates, score-only explanation
masking, append-only feedback history, drift-state rehydration, consistent
error envelopes, request IDs, database-waking 503 behavior, and generated
OpenAPI/TypeScript contracts.

The authorization and OpenAPI contract tests passed. Database-backed API
modules were skipped without TEST_DATABASE_URL, so the configured 85 percent
CI coverage gate was not demonstrated locally.

### Phase 6 - showcase preparation

The artifacts-only preparation path completed with 20,000 deterministic
synthetic rows, all three model families, model version
s2-28c97cfc828c4af8, and a real sample score of 0.461977. The generated model
is marked synthetic. The Neon migration and seed portion was not run against
the configured showcase database.

### Phase 7 - frontend rebuild

Implemented the routed, permission-gated React application with the
application wizard, searchable/paginated applications, both review study-arm
views, decision amendments and history, monitoring and KS workflow,
retraining review, model/study pages, user/role/audit administration, and the
How it works page. Monitoring is manually refreshed; static source inspection
found no automatic polling interval.

Vitest passed 14 files and 19 tests. The production build completed with zero
warnings. A manual role-by-role browser walkthrough was not performed.

### Phase 8 - full-stack verification

The executable UI/API contract and authorization-matrix checks passed. The
Playwright suite contains 11 real-stack acceptance tests and was discovered
successfully. It was not run against a live stack because there is no isolated
TEST_DATABASE_URL and the showcase database must not be used for destructive
or mutating acceptance tests.

No controlled Neon cold-start measurement, idle Neon console observation,
live restart/rehydration test, or warm/cold prediction timing was performed.

### Phase 9 - documentation and showcase kit

The repository includes the local-plus-Neon README, one-command PowerShell and
shell setup/start wrappers, architecture and RBAC references, a showcase
walkthrough, the full-stack contract, and an optional read-only JSON export.
The README now states how to enable Playwright only for a migrated, seeded,
isolated test branch.

The launchers were reviewed and parsed, but neither one-command workflow was
executed end to end against a live database.

## Final verification table

| Check | Exact command | Observed result |
| --- | --- | --- |
| Python lint | .\.venv\Scripts\python.exe -m ruff check . | Passed: All checks passed |
| Python compilation | .\.venv\Scripts\python.exe -m compileall -q backend scripts tests src | Passed, exit 0 |
| Backend/core tests | .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .tmp\p249d | Passed: 66 passed, 2 skipped, 28 warnings in 29.35 s |
| Alembic revision regression | .\.venv\Scripts\python.exe -m pytest -q tests\test_database_config.py | Passed; head `0003_rbac_feedback_history` is 26 characters and fits `VARCHAR(32)` |
| Offline migration compile | `$env:DIRECT_DATABASE_URL=<non-routable placeholder>; .\.venv\Scripts\python.exe -m alembic upgrade head --sql` | Passed; generated the `0002` to `0003_rbac_feedback_history` version update without connecting to Neon |
| Coverage measurement | .\.venv\Scripts\python.exe -m pytest -q --basetemp .tmp\pytest-coverage -p no:cacheprovider --cov=drift_loan --cov=backend --cov-report=term-missing | 65 passed, 2 skipped; TOTAL 70 percent because database/API modules were skipped |
| Authorization contract | .\.venv\Scripts\python.exe -m pytest -q tests\test_authorization_contract.py | Passed: 1 passed |
| OpenAPI contract | .\.venv\Scripts\python.exe -m pytest -q tests\test_openapi_contract.py | Passed: 1 passed |
| Demo artifact preparation | .\.venv\Scripts\python.exe scripts\prepare_demo.py --artifacts-only | Passed: 20,000 rows, three model families, real score path exercised |
| Frontend lint and TypeScript | npm --prefix frontend run lint | Passed with zero warnings |
| Frontend unit tests | npm --prefix frontend run test -- --run | Passed: 14 files, 19 tests; duration 155.65 s |
| Frontend production build | npm --prefix frontend run build | Passed: 3,651 modules; completed in 16.99 s with zero warnings |
| Playwright discovery | npm --prefix frontend run test:e2e -- --list | Passed: 11 tests discovered |
| Real-stack Playwright | E2E_REAL_STACK=true with isolated TEST_DATABASE_URL, then npm --prefix frontend run test:e2e | Not run: isolated test branch URL is not configured |
| Direct and pooled Neon check | .\.venv\Scripts\python.exe scripts\check_db.py --pooled | Connectivity and 25-query probe passed; command correctly exited non-zero because migration is behind |
| Live Alembic model diff | .\.venv\Scripts\python.exe -m alembic check | Not run: requires the guarded isolated test branch |
| One-command setup | .\scripts\dev-setup.ps1 | Not run end to end: it would migrate and seed live Neon |
| One-command start | .\scripts\dev-start.ps1 | Not run end to end while the configured database is behind |

The two pytest skips are the guarded database modules
tests/test_backend.py and tests/test_neon_database.py. They require a separate
direct TEST_DATABASE_URL. The 28 warnings were one Starlette anyio deprecation
warning and 27 scikit-learn solver warnings; they did not fail the suite.

The CI command retains --cov-fail-under=85. A 70 percent local measurement is
not evidence that the 85 percent gate passes; the database-backed test branch
run is still required.

## Measured Neon results

| Observation | Result |
| --- | --- |
| Direct endpoint | PostgreSQL 16.15, TLS in use, gen_random_uuid available |
| Direct connection/check latency | 7,147.2 ms |
| Pooled connection/check latency | 6,084.1 ms |
| Pooled prepared-statement safety probe | 25 repeated queries passed |
| Current Alembic revision | 0002_rbac_audit_schema |
| Expected Alembic head | 0003_rbac_feedback_history |
| Controlled cold start | Not measured |
| Idle UI traffic in Neon console/logs | Not measured |

The measured connection times may include wake-up time, but the compute was
not deliberately suspended or observed idle first. They must not be described
as cold-start measurements.

## Findings F1-F13

| Finding | Status | Reason |
| --- | --- | --- |
| F1 SQLite default and no migrations | Partly fixed | Source uses required Neon URLs and Alembic only; the live showcase is still one migration behind |
| F2 No shipped model | Fixed | One-command preparation builds the synthetic demo bundle; artifacts-only execution produced a loadable real-model score |
| F3 Bad applicant input returned 503 | Fixed | Field validation maps applicant errors to 422; 503 remains for model/infrastructure faults |
| F4 Frontend/backend validation drift | Fixed | Wizard is driven by the backend reference schema and maps server 422 errors to fields |
| F5 One-page UI and missing workflows | Fixed | Routed permission-aware pages cover review, monitoring, retraining, and administration workflows |
| F6 Open registration and string roles | Fixed | Registration takeover is removed; roles/permissions are relational and admin-managed |
| F7 JWT/hash/token handling | Fixed | Required JWT secret, Argon2id migration, sessionStorage, lockout, and global 401 handling are implemented |
| F8 In-memory drift reset | Partly fixed | Persistence and rehydration exist and single-worker operation is documented; live restart behavior was not exercised |
| F9 Dead Redis/Celery infrastructure | Fixed | Queue/cache dependencies and worker topology were removed |
| F10 Repeated ambiguous feedback | Fixed | Feedback is append-only/versioned with current-decision semantics and amendment/override notes |
| F11 Fake-only model/API tests | Partly fixed | The real artifact path was exercised, but DB-backed modules skipped and total local coverage was 70 percent |
| F12 Stale frontend monitoring contract | Fixed | OpenAPI is committed, TypeScript is generated, and the executable contract test passed |
| F13 Generic DB types | Partly fixed | PostgreSQL-native models and migration exist; migration 0003 has not been applied to the live showcase |

## New verification findings

| Finding | Status | Consequence |
| --- | --- | --- |
| N1 No TEST_DATABASE_URL in the current environment | Open | Destructive migration round trip, live database suite, and real-stack E2E cannot run safely |
| N2 Showcase database is behind Alembic head | Open | API startup should refuse until migration 0003 is explicitly applied |
| N3 Coverage gate not reproduced locally | Open | The observed 70 percent does not satisfy the configured 85 percent CI threshold |
| N4 No controlled cold/idle observation | Open | Cold-start recovery and zero background Neon traffic remain code/static evidence only |

## Assumptions and design choices

- Redis and Celery were removed because they served only the unused healthcheck
  worker.
- React 18, React Router, TanStack Query, Ant Design 5, Recharts, zod, MSW,
  and Playwright were retained or added for the requested corporate UI.
- Each user has one role. Permissions are many-to-many through the role.
- The showcase runs one API worker so in-process detector state cannot diverge.
- CI was retained and is expected to receive a dedicated Neon test-branch
  secret, never the showcase URL.
- Current Neon plan limits were not verified in the console during this run;
  the implementation avoids depending on a numeric branch or storage quota.
- Retraining approval creates an auditable human decision and never starts
  training automatically.

## Work still requiring explicit live-environment authorization

1. Supply a direct TEST_DATABASE_URL for a separate Neon branch.
2. Run the guarded migration round trip, alembic check, database-backed pytest
   modules, and the real-stack Playwright suite on that branch.
3. Explicitly authorize applying migration 0003 and seeding the configured
   showcase database.
4. Start the complete stack, verify all four logins, and perform the
   role-by-role browser walkthrough.
5. Deliberately suspend or idle Neon, measure recovery, and then leave the UI
   idle while observing Neon/logs for background traffic.

## Safe real-stack Playwright invocation

First start a migrated and seeded API/UI stack against the dedicated test
branch. In the Playwright terminal, use the direct test-branch URL. The URL and
passwords shown here are placeholders:

    $env:TEST_DATABASE_URL = "postgresql://TEST_USER:***@ep-test.REGION.aws.neon.tech/TEST_DB?sslmode=require"
    $env:E2E_REAL_STACK = "true"
    $env:E2E_ADMIN_PASSWORD = "***"
    $env:E2E_ANALYST_PASSWORD = "***"
    $env:E2E_EXPLAIN_PASSWORD = "***"
    $env:E2E_SCORE_ONLY_PASSWORD = "***"
    npm --prefix frontend run test:e2e

The suite rejects pooled TEST_DATABASE_URL values and a test target matching
an exported showcase target. Without E2E_REAL_STACK=true it is intentionally
skipped.

## Showcase start commands

After the database has been migrated to head and seeded:

    .\scripts\dev-start.ps1

Or start the processes in separate PowerShell terminals:

    .\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1

    npm --prefix frontend run dev -- --host 127.0.0.1

Credentials remain in the ignored environment file and are masked here:

| Username | Password |
| --- | --- |
| admin | *** |
| analyst | *** |
| officer.explain | *** |
| officer.scoreonly | *** |
