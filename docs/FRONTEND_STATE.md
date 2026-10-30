# Frontend State

Read this first when opening a new chat. Updated at the end of each phase.

## Phase

F-2a — attendance sheet with filters and monthly grid. Real page replaces the /attendance placeholder.

## Bundles done

F-0a, F-0b + f002-fix, F-1a + f003-fix, B-1 + B-1-fix-2, F-1b + f004-fix + f004-fix2, F-2a (this bundle).

## Bundle plan (13 frontend bundles remaining)

F-2a ✓ | F-2b (day panel, daily list, mark reviewed) | F-3a, F-3b | F-4a, F-4b | F-5a, F-5b | F-6 | F-8 | F-7a, F-7b (waits for B-4).

## Backend requests

| # | Request | Blocks | Status |
|---|---|---|---|
| B-1 | GET /auth/me | F-1b | DELIVERED |
| B-2 | Demo seed via real engine | Demo data | PENDING |
| B-3a | GET /payroll/pay-periods/{id}/preview/{employee_id} | F-7b | PENDING |
| B-3b | Own-payslips endpoint | F-7b | PENDING |
| B-4 | Attendance-to-earnings | F-7 | PENDING |

## Important contracts

- /auth/login returns `{access_token, refresh_token, token_type, expires_in}` only. No must_change_password. UI uses /auth/me.
- /auth/me returns `{id, username, role, employee_id, permissions[], must_change_password}`.
- Usernames: normalise_username strips separators when a digit is present. Use `paone` not `pa-1`.
- Refresh uses `csrf_token` cookie + `csrf_protection`. Client does NOT yet send the CSRF header. Refresh will 403 until fixed. Flagged.
- Attendance sheet: `GET /api/v1/attendance/sheet?from_date=&to_date=&site_id=&branch_id=&department_id=&include_terminated=&limit=&cursor=` → `{items: SheetEmployee[], next_cursor}` where SheetEmployee = `{employee_id, employee_code, employee_name, site_id, department_id, days: SheetCell[]}` and SheetCell = `{work_date, status, worked_minutes, normal_minutes, overtime_minutes, flags, open_exception_count, locked, reviewed}`. Client logs a console.warn if the shape doesn't match at runtime. Field names assumed from the backend spec; verify on first live run.

## Verified gaps

Only B-2, B-3a, B-3b, B-4 remain. Attendance sheet field names not verified against a live response — client warnShapeMismatch prints the mismatch to console if backend differs.

## Decisions

- Attendance sheet uses `wrappedFetch` + manual type cast (not `api.GET`) until `npm run api:types` is run against a live backend. When the schema is generated, F-2a's `api/attendance.ts` types become authoritative.
- Attendance status chip is a client-side post-filter (`attendanceStatus` in page state) layered over the sheet response.
- Employee-status filter is `includeTerminated` only (backend supports that).
- Sheet cell tooltip surfaces minutes, flags, open exception count, locked, reviewed — colour is never the only signal (status text + tooltip).
- Pagination: "first page" (clears cursor) and "next page" (uses next_cursor). No "previous" — cursor is forward-only.
- No row virtualisation yet (20 employees × 31 days = 620 cells, fine at this size).
- No day panel yet — F-2b.

## Next step

F-2b: day panel (open a cell, fetch `GET /attendance/day/{employee_id}/{work_date}` if it exists, else use `GET /punches` filtered), daily list view, bulk `mark clean days reviewed` with refused-days table. Requires B-2 for realistic data to exercise the flow. If B-2 has not landed, F-2b ships against empty data (screens render, error states tested).
