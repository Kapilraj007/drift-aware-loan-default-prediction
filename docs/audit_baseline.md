# Phase 1 baseline audit

Audit date: 2026-10-02. This report records the repository before Phase 2 and
Phase 3 implementation. No credential values were printed or copied.

## Executed baseline

| Check | Result | Evidence excerpt |
| --- | --- | --- |
| Python environment | Passed | Existing `.venv` reported Python 3.12.14 |
| Install | Passed | `pip install -r requirements-dev.txt` and editable install completed |
| Ruff | Passed | `All checks passed!` |
| Pytest, host defaults | Environment failure | 43 passed; 16 setup errors because the account could not access pytest's default temp/cache directory |
| Pytest, workspace temp | Product-test failure | 58 passed, 1 failed: explanation availability was asserted despite a randomized score-only assignment |
| Frontend lint | Passed | TypeScript and ESLint exited 0 with zero warnings |
| Frontend unit tests | Passed | 10 files, 13 tests |
| Frontend build | Passed | 42 modules; production bundle generated |
| Synthetic feature build | Passed | 400 rows read; 363 resolved; 219/73/71 temporal split |
| Synthetic model training | Passed | LightGBM, XGBoost, logistic regression, SHAP and ADWIN artifacts written |
| Baseline API flow | Passed | login, application persistence, real prediction, liveness and readiness completed |
| Browser click-through | Not verified | UI-control runtime failed during initialization with a host sandbox helper error |

The initial test command was repeated with `--basetemp` under the workspace
and the cache plugin disabled. This separated the host permission failure from
the actual nondeterministic test defect.

## Findings F1–F13

| ID | Baseline status | Severity | Evidence | Planned fix |
| --- | --- | --- | --- | --- |
| F1 | Confirmed | Critical | Runtime config defaulted to an embedded local DB; startup called metadata schema creation; no migration directory existed | Phase 3 |
| F2 | Confirmed for clean checkout | Critical | Tracked artifact directories contain placeholders only; generated local artifacts were ignored working files | Phase 6 |
| F3 | Confirmed by code path | High | Transformer parse failures become `ModelArtifactError`; prediction route maps that class to 503 | Phase 5 |
| F4 | Confirmed | High | Frontend date parsing and field coverage do not mirror the backend transformer | Phase 7 |
| F5 | Confirmed | High | Single-page UI; endpoint inventory shows history/detail/admin gaps | Phase 7 |
| F6 | Confirmed | Critical | First registration becomes admin; role is a string; no management API | Phase 4 |
| F7 | Confirmed | High | Default JWT secret, browser persistent storage, no global 401 flow, hand-rolled PBKDF2 | Phases 4 and 7 |
| F8 | Confirmed | High | ADWIN/latest KS state are process memory; UI maps `not_observed` to Watch | Phases 5 and 7 |
| F9 | Confirmed | Medium | Queue/cache dependencies supported only a worker healthcheck stub | Phase 2 |
| F10 | Confirmed | High | No database uniqueness rule or route guard for a second decision | Phase 3 |
| F11 | Confirmed | High | Backend API tests substitute inference/SHAP; coverage targeted only the core package | Phases 3, 6, and 8 |
| F12 | Confirmed | Medium | Frontend source union differs from the two backend values | Phase 7 |
| F13 | Confirmed | Medium | IDs, JSON, and timestamps used portability-oriented rather than PostgreSQL-native types | Phase 3 |

## New findings

| ID | Status | Severity | Detail | Disposition |
| --- | --- | --- | --- | --- |
| N1 | Confirmed | Medium | A baseline backend test expected explanations unconditionally even though the durable A/B assignment can be score-only | Fixed while moving the suite to the Phase 3 test branch |
| N2 | Confirmed, host-specific | Low | Pytest's default Windows temp/cache directories are inaccessible to this account | Use a workspace-local `--basetemp`; not a product change |
| N3 | Confirmed | Low | The installed global Python is 3.14 and outside project bounds, while the existing project venv is the required 3.12.14 | All project commands use the venv explicitly |
| N4 | Confirmed | Medium | `npm ci` reported three moderate dependency-audit findings | Not changed automatically because the suggested forced update may be breaking; review in a later dependency-maintenance change |

## Phase 1 gate

The baseline report exists with real command output. The baseline was not
fully green: N1 was a genuine test defect and the default temp location was
blocked by host permissions. Both facts are retained rather than reported as
passes.
