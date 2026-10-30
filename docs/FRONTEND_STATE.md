# Frontend State

Read this first when opening a new chat. Updated at the end of each phase.

## Phase

F-1b — shell, auth/me integration, role-aware nav, landing cards. Login flow now correctly reaches /change-password when the backend flags must_change_password on /auth/me (login response does not carry the flag).

## Bundles done

F-0a (tooling), F-0b + f002-fix (scaffold, typed client, error mapper, theme, strings), F-1a + f003-fix (login/auth/password), B-1 + B-1-fix-2 (backend GET /auth/me), F-1b (this bundle).

## Bundle plan (14 frontend bundles remaining)

F-0a ✓, F-0b ✓, F-1a ✓, F-1b ✓ | F-2a, F-2b | F-3a, F-3b | F-4a, F-4b | F-5a, F-5b | F-6 | F-8 | F-7a, F-7b (waits for B-4).

## Backend requests

| # | Request | Blocks | Status |
|---|---|---|---|
| B-1 | GET /auth/me returning id, username, role, employee_id, permissions[], must_change_password. | F-1b | DELIVERED |
| B-2 | Demo seed via real engine, tracked at backend/app/seed/demo_seed.py, --reset/--keep, refuse in prod, fictional SA names, real exception types only, docs/SEED.md. | Demo data for F-2..F-4 | PENDING |
| B-3a | GET /payroll/pay-periods/{id}/preview/{employee_id}. | F-7b (tab hidden) | PENDING |
| B-3b | Own-payslips endpoint for employee role via SELF_VIEW. | F-7b | PENDING |
| B-4 | Attendance-to-earnings. | F-7 fully | PENDING |

## Important contracts

- Login response: `{access_token, refresh_token, token_type, expires_in}`. **No `must_change_password`**. UI relies on `/auth/me` for role, permissions, must_change_password.
- `/auth/me` response: `{id, username, role, employee_id, permissions[], must_change_password}`. Permissions from the live ROLE_PERMISSIONS matrix.
- Usernames: `normalise_username` strips separators when a digit is present (mobile heuristic). Use usernames without digit+separator mixes (`admin`, `paone`, `hrself`). `pa-1` becomes `pa1`.
- Refresh: uses `csrf_token` cookie and a `csrf_protection` dependency. **Client currently does NOT send the CSRF header.** Refresh may 403 until the client reads the cookie and echoes it. To verify at F-2 setup or earlier if login-expiry is tested.
- `X-Tenant-Slug` sent on login, refresh, logout, me (client.ts handles).

## Verified gaps

Only B-2, B-3a, B-3b, B-4 remain. Refresh CSRF header is a known under-implementation (client.ts, FRONTEND_STATE above).

## To verify at relevant phase

CSRF header name and source; GET /attendance/day/{employee_id}/{work_date}; GET /punches; nine audit filters; two-step import token; device api_key in 201 only; dry-run token TTL; row_version in each PATCH-able GET.

## Decisions

- Role gating: driven by `me.permissions` (B-1) only. Never hard-code.
- Placeholder pages exist for every nav link so the shell navigates without 404. Each placeholder names its target phase.
- Landing cards derived from permissions; no live counts yet. Counts land in F-2/F-3 once those pages fetch and cache the lists.
- Role-aware nav filtered by permission (see `shell/nav.ts`), not by role name.
- Preview detail: hidden until B-3a.
- Import wizard: two steps.
- Sheet status filter: employee-status + attendance-status chip (client-side post-filter).
- Version pinning: caret ranges; package-lock.json is the real pin.

## Next step

F-2a (attendance sheet filters + monthly grid). Requires B-2 (demo seed) for realistic data to render against. If B-2 has not landed, F-2a is still deliverable (screens render empty and error states), but the demo cannot be exercised. Ship F-2a now, plan B-2 for after.
