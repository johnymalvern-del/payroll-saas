# Frontend State

Read this first when opening a new chat. Updated at the end of each phase.

## Phase

F-1a — delivered in f003-fix (login + forced password change + auth provider + protected routes). F-1b (auth/me, shell, landing cards) waits for B-1.

## Bundles done

F-0a (tooling), F-0b + f002-fix (scaffold, typed client, error mapper, theme, strings), F-1a + f003-fix (login/auth/password).

## Bundle plan (16 total, unchanged)

F-0a done, F-0b done, F-1a done, F-1b next (waits for B-1) | F-2a, F-2b | F-3a, F-3b | F-4a, F-4b | F-5a, F-5b | F-6 | F-8 | F-7a, F-7b (waits for B-4).

## Backend requests

| # | Request | Blocks |
|---|---|---|
| B-1 | GET /auth/me returning id, username, role, employee_id, permissions[], must_change_password. | F-1b |
| B-2 | Demo seed via real engine, tracked at backend/app/seed/demo_seed.py with wrapper scripts/seed_demo.ps1, --reset/--keep, refuse in prod, fictional SA names, fake tax numbers, real exception types only, credentials in docs/SEED.md. | Demo data |
| B-3a | GET /payroll/pay-periods/{id}/preview/{employee_id}. | F-7b (tab hidden) |
| B-3b | Own-payslips endpoint for employee role via SELF_VIEW. | F-7b |
| B-4 | Attendance-to-earnings integration. | F-7 fully |

## Verified gaps

Same as B-1, B-3a, B-4 above. F-1a assumes login response is `{access_token: string, must_change_password?: boolean}` and change-password body is `{current_password, new_password}`. If either assumption is wrong, F-1a-fix-2 corrects it.

## To verify at relevant phase

Refresh CSRF header name/value; login response exact shape; change-password body shape; GET /attendance/day/{employee_id}/{work_date}; GET /punches; nine audit filters; two-step import token; device api_key in 201 only; dry-run token TTL; row_version in each PATCH-able GET; `X-Tenant-Slug` on /auth/login and /auth/refresh.

## Decisions

- Role gating: use B-1 /auth/me, never hard-code permissions. F-1b adds role-aware nav.
- Preview detail: hidden until B-3a.
- Import wizard: two steps.
- Sheet status filter: employee-status + attendance-status chip (client-side post-filter).
- Node 20 assumed; apply_bundle.py --frontend halts if < 20.
- Version pinning: caret ranges; package-lock.json is the real pin.

## Known non-blocking quirks

- apply_bundle.py's frontend table occasionally omits a written row from the display (strings.ts in f003). File is written to disk; commit is unaffected. Not chased. If it happens on a commit that matters, note it and add the file explicitly to a follow-up bundle.

## Next step

Wait for B-1 (GET /auth/me) before starting F-1b. To test F-1a end-to-end now:
  1. Start backend: `cd backend; python -m uvicorn app.main:app --reload --port 8000`
  2. Start frontend: `cd frontend; npm run dev`
  3. Open http://127.0.0.1:5173
  4. Try login with demo tenant credentials.

If the backend is not seeded (B-2 pending), F-1a is code-complete and unit-tested but cannot demonstrate the full login flow until a user exists.
