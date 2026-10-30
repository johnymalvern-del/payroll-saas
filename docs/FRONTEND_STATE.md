# Frontend State

Read this first when opening a new chat. Updated at the end of each phase.

## Phase

F-1a done (login + forced password change + auth provider + protected routes). B-1 delivered (GET /auth/me), fixing back to green after fixing the login-username normalisation trap. Next: F-1b (auth/me integration, shell, role-aware nav, landing cards).

## Bundles done

F-0a (tooling), F-0b + f002-fix (scaffold, typed client, error mapper, theme, strings), F-1a + f003-fix (login/auth/password), B-1 + B-1-fix-2 (backend: GET /auth/me).

## Bundle plan (16 frontend bundles)

F-0a done, F-0b done, F-1a done, F-1b next | F-2a, F-2b | F-3a, F-3b | F-4a, F-4b | F-5a, F-5b | F-6 | F-8 | F-7a, F-7b (waits for B-4).

## Backend requests

| # | Request | Blocks | Status |
|---|---|---|---|
| B-1 | GET /auth/me returning id, username, role, employee_id, permissions[], must_change_password. | F-1b | DELIVERED |
| B-2 | Demo seed via real engine, tracked at backend/app/seed/demo_seed.py with wrapper scripts/seed_demo.ps1, --reset/--keep, refuse in prod, fictional SA names, fake tax numbers, real exception types only, credentials in docs/SEED.md. | Demo data (F-2..F-4) | PENDING |
| B-3a | GET /payroll/pay-periods/{id}/preview/{employee_id}. | F-7b (tab hidden) | PENDING |
| B-3b | Own-payslips endpoint for employee role via SELF_VIEW. | F-7b | PENDING |
| B-4 | Attendance-to-earnings integration. | F-7 fully | PENDING |

## Verified gaps

Only B-2, B-3a, B-3b, B-4 remain.

## Important: login response shape

The backend's `/auth/login` response returns ONLY `access_token`, `refresh_token`, `token_type`, `expires_in`. It does **NOT** return `must_change_password`. Therefore F-1a's `AuthProvider.login()` always sees `mustChangePassword = false` from the login response, and the change-password redirect only fires after the app calls `/auth/me`.

**F-1b must therefore**: after login succeeds, immediately call `/auth/me` (or load a `useMe()` hook that does). If `must_change_password` is true, redirect to `/change-password` before rendering the home shell. Do not rely on the login response for that flag.

Same for role-based navigation: F-1b must gate nav on the `/auth/me` payload's `permissions[]`, never on any client-side hard-coded map.

## To verify at relevant phase

Refresh CSRF header name/value (backend uses `csrf_protection` dependency on /auth/refresh and /auth/logout; the client must read the `csrf_token` cookie and echo it in a header — name to confirm); GET /attendance/day/{employee_id}/{work_date}; GET /punches; nine audit filters; two-step import token; device api_key in 201 only; dry-run token TTL; row_version in each PATCH-able GET; `X-Tenant-Slug` on /auth/login, /auth/refresh, /auth/logout, /auth/me.

## Decisions

- Role gating: B-1 delivers it; F-1b uses it. Never hard-code permissions.
- Preview detail: hidden until B-3a.
- Import wizard: two steps.
- Sheet status filter: employee-status + attendance-status chip (client-side post-filter).
- Node 20 assumed; apply_bundle.py --frontend halts if < 20.
- Version pinning: caret ranges; package-lock.json is the real pin.

## Known non-blocking quirks

- apply_bundle.py's frontend table occasionally omits a written row (strings.ts in f003). File is written to disk; commit unaffected.
- f003 TSC failure (refreshAccessToken not async) fixed in f003-fix.
- Login does NOT accept usernames with digits and separators mixed (normalise_username collapses them to strip separators as if a mobile number). Use `paone` not `pa-1`. This is intentional backend behaviour, not a bug — document for future testers and demo credentials.
- `/auth/me` reads the `User.must_change_password` column with a `password_changed_at is None` fallback. Both are consistent today.

## Next step

F-1b: build `useMe()` TanStack Query hook, call it after login (and on protected route mount), and (a) redirect to `/change-password` if `must_change_password` is true, (b) render role-aware navigation from `permissions[]`, (c) replace the inline HomePage with a proper shell and landing cards. Report the tool table after:
  python tools\apply_bundle.py bundles\f004.txt --frontend --commit "F-1b: auth/me integration + shell + role-aware nav + landing cards"
