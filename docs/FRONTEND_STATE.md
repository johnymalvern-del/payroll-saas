# Frontend State

Read this first when opening a new chat. Updated at the end of each phase.

## Phase

F-2 complete (F-2a sheet + F-2b day panel/daily/mark-reviewed, all green: 8 tests in `AttendanceSheetPage.test.tsx`). Tool gap closed in f007: `--also` files are now inside the frontend tsc/vitest gate scope, so a source-only bundle still exercises the corresponding test file. Next: F-3a.

## Bundles done

F-0a, F-0b, F-1a, F-1b (+ fixes), F-2a (+ fixes f005-fix..f005-fix4), F-2b (+ fixes f006-fix..f006-fix6), f007 (this bundle, tool fix).

## Bundle plan (11 frontend bundles remaining)

F-3a, F-3b | F-4a, F-4b | F-5a, F-5b | F-6 | F-8 | F-7a, F-7b (waits for B-4).

## Backend requests

| # | Request | Blocks | Status |
|---|---|---|---|
| B-1 | GET /auth/me | — | DELIVERED |
| B-2 | Demo seed via real engine | Demo data | PENDING |
| B-3a | GET /payroll/pay-periods/{id}/preview/{employee_id} | F-7b | PENDING |
| B-3b | Own-payslips endpoint | F-7b | PENDING |
| B-4 | Attendance-to-earnings | F-7 | PENDING |

## Important contracts

- `/auth/login` returns `{access_token, refresh_token, token_type, expires_in}` only. UI uses `/auth/me` for role + permissions + must_change_password.
- `/auth/me` returns `{id, username, role, employee_id, permissions[], must_change_password}`.
- Usernames: `normalise_username` strips separators when a digit is present. `pa-1` → `pa1`.
- Refresh: CSRF header still missing on client. Flagged since F-1a.
- **`new Request(relativeUrl)` throws in jsdom/Node.** All manual requests go through `absoluteUrl()` in `client.ts`.
- Attendance sheet/daily/day/mark_reviewed field shapes normalised defensively in `attendance.ts` (`normaliseSheetOut`, `normaliseDailyOut`, `normaliseDayOut`, `warn`).
- **Clickable grid cell has `data-testid={`cell-${employeeId}-${workDate}`}`.** Tests must use that testid. Never DOM-traverse from a Badge — Mantine Tooltip wrapping makes that unreliable.
- Sheet tests must derive fixture dates from `dayjs()` (`TODAY`) so the cell falls in the default visible month.
- Mark-reviewed flow is page button → modal opens → modal submit. Two clicks required.
- Mantine Tooltip must wrap the clickable div (not be its child) — see f006-fix5 for why.

## Verified gaps

Only B-2, B-3a, B-3b, B-4 remain.

## Decisions

- Grid cell click targets `data-testid` wrapper — future Badge/Tooltip composition changes won't break tests.
- Fixture dates always derived from `dayjs()`.
- Adjustment markers never appear on grid, daily list, or day panel (C2).
- Attendance status filter is a client-side post-filter.
- No row virtualisation yet.

## Tool behaviour (f007)

- `--also <path>` now extends the frontend tsc/vitest **gate scope** in addition to being included in `--commit`.
- Filtered to `frontend/` paths; non-frontend `--also` args (e.g. `docs/FRONTEND_STATE.md`) do not affect gates.
- `npm install` still runs **only** on bundle-written `frontend/package.json` (passing package.json via `--also` is not treated as a change signal — avoids slow installs).
- Consequence: F-3a can now write only source files and pass the corresponding test file via `--also`; tsc and vitest will still exercise it.

## Next step

F-3a: exceptions queue with type chips and suggested fixes; single adjustment form (outcome, worked/leave/sick/absent/day_off; times; reason_code; note required when reason_code is "other"); inline handling of `cannot_adjust_own` (403) and `day_locked` (409). Add `frontend/src/api/exceptions.ts` and `frontend/src/api/adjustments.ts`, plus pages and forms. Tests must use `data-testid` on the exception row and adjustment buttons; fixture dates from `dayjs()`.
