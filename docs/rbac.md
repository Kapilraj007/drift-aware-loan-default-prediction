# Roles and permissions

Authorization is table-driven. `roles`, `permissions`, and
`role_permissions` are seeded idempotently; routes depend on permission codes,
not role names. Ownership remains an explicit application rule: a loan officer
can read only their own applications, predictions, and feedback, while the
`*:read_all` permissions lift that scope.

| Permission | Loan officer | Risk analyst | Admin |
| --- | :---: | :---: | :---: |
| `application:create` | yes | yes | yes |
| `application:read_own` | yes |  |  |
| `application:read_all` |  | yes | yes |
| `prediction:create` | yes | yes | yes |
| `prediction:read_own` | yes |  |  |
| `prediction:read_all` |  | yes | yes |
| `feedback:create` | yes | yes | yes |
| `feedback:read_own` | yes |  |  |
| `feedback:read_all` |  | yes | yes |
| `experiment:participate` | yes |  |  |
| `experiment:read_results` |  | yes | yes |
| `monitoring:read` |  | yes | yes |
| `monitoring:run_check` |  | yes | yes |
| `retraining:create` |  | yes | yes |
| `retraining:read` |  | yes | yes |
| `retraining:review` |  |  | yes |
| `model:read` |  | yes | yes |
| `dashboard:read` | yes | yes | yes |
| `user:manage` |  |  | yes |
| `role:read` |  |  | yes |
| `audit:read` |  |  | yes |

`GET /api/v1/auth/me` returns the assigned role and a sorted permission list.
The React application uses that list to hide or guard navigation, but the API
remains the authority and returns 403 for denied actions and cross-owner reads.

## Security invariants

- There is no public registration or first-user-becomes-admin path.
- The explicit seed is the administrative bootstrap path; normal user creation
  is admin-only through `POST /api/v1/users`.
- The last active admin cannot be deactivated or demoted, and an admin cannot
  deactivate their own current account.
- Deactivated users are rejected on their next request.
- Passwords use Argon2id. A valid legacy PBKDF2 login is transparently
  rehashed.
- Repeated failed logins cause a timed lock; the response remains generic.
- Password reset values are returned once and are never written to audit
  metadata or logs.

## Adding a permission

1. Add a stable `PermissionCode` value and description to the catalogue in
   `backend/app/core/rbac.py`.
2. Add it to the intended system-role mappings.
3. Protect the route/action with `require_permissions(...)` and keep any
   ownership rule in the route or service.
4. Add an Alembic data migration when existing deployed databases must receive
   the new catalogue before the seed can run.
5. Run the seed to reconcile additions and removals.
6. Extend the generated endpoint-by-role matrix test and the frontend route or
   action guard.

## Adding a role

1. Create an Alembic data migration for the role and its initial grants.
2. Add the role to the seed catalogue with a description and explicit
   permissions.
3. Decide whether it gets own-record or all-record scope; never infer this from
   a similar role name.
4. Extend API authorization/ownership tests, navigation tests, and this matrix.
5. Run `python -m backend.app.db.seed --yes` against the intended direct Neon
   endpoint and verify `/auth/me` with a dedicated account.

Never edit role grants directly on the showcase branch as an undocumented
one-off. Catalogue changes belong in source, migration/seed logic, and tests.
