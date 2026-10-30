# Frontend State

Read this first when opening a new chat. Updated at the end of each phase.

## Phase

F-0b — scaffold delivered (bundle f002 pending run).

## Bundle plan (16 total)

F-0a done (tooling), F-0b (scaffold, this bundle) | F-1a, F-1b (auth/shell) | F-2a, F-2b (attendance) | F-3a, F-3b (exceptions/adjustments) | F-4a, F-4b (employees/import) | F-5a, F-5b (setup) | F-6 (pay setup) | F-8 (audit) | F-7a, F-7b (payroll; waits for B-4)

Order: F-0, F-1, F-2, F-3, F-4, F-5, F-6, F-8, F-7. F-1b waits for B-1.

## Backend requests

| # | Request | Blocks |
|---|---|---|
| B-1 | GET /auth/me returning id, username, role, employee_id, permissions[], must_change_password. Frontend MUST NOT hard-code permissions. | F-1b |
| B-2 | Demo seed via real engine, tracked at backend/app/seed/demo_seed.py with wrapper scripts/seed_demo.ps1, --reset/--keep, refuse in prod, fictional SA names, fake tax numbers, real exception types only, credentials in docs/SEED.md. | Demo data |
| B-3a | GET /payroll/pay-periods/{id}/preview/{employee_id} per-employee detail. | F-7b (tab hidden until then) |
| B-3b | Own-payslips endpoint for employee role via SELF_VIEW (may work today via apply_scope on /payroll/payslips; confirm). | F-7b (My payslips tab) |
| B-4 | Attendance-to-earnings: per_hour from attendance_segment minutes x stored rates, overtime/premiums, six formulas from runner, refusal on setup_error / unreconciled_leave, reimbursements source. | F-7 fully |

## Verified gaps (against backend code, not openapi)

Same as B-1, B-3a, B-4 above.

## To verify at relevant phase

Login response shape; refresh CSRF header name/value; must_change_password in login response; GET /attendance/day/{employee_id}/{work_date}; GET /punches; nine audit filters; two-step import token; device api_key in 201 only; dry-run token TTL; row_version in each PATCH-able GET.

## Decisions

- Role: use B-1 /auth/me, never hard-code permissions.
- Preview detail: hidden until B-3a.
- Import wizard: two steps.
- Sheet status filter: employee-status + attendance-status chip (client-side post-filter).
- Node 20 assumed; apply_bundle.py --frontend halts if < 20.
- Version pinning: caret ranges within known-good majors; package-lock.json is the real pin.

## Verified gaps (unresolved)

- B-1, B-3a, B-4 as above.
- Refresh response shape and CSRF header unverified. client.ts uses a defensive access_token key check and does not send a CSRF header; if the backend requires one, that is the fix location.

## Next step

Run: python tools\apply_bundle.py bundles\f002.txt --frontend --also frontend/package-lock.json --commit "F-0b: scaffold + typed client + error mapper + theme"

Report the table. If green, F-1a is next (login page; no role gating yet, waits for B-1 at F-1b).
