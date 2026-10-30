# Frontend State

Read this first when opening a new chat. Updated at the end of each phase.

## Phase

F-2b — day panel, daily list, mark clean days reviewed. F-2a is on disk and green (see commit history).

## Bundles done

F-0a, F-0b, F-1a, F-1b (+ fixes), F-2a (+ fixes f005-fix through f005-fix4), F-2b (this bundle).

## Bundle plan (12 frontend bundles remaining)

F-2b ✓ | F-3a, F-3b | F-4a, F-4b | F-5a, F-5b | F-6 | F-8 | F-7a, F-7b (waits for B-4).

## Backend requests

| # | Request | Blocks | Status |
|---|---|---|---|
| B-1 | GET /auth/me | — | DELIVERED |
| B-2 | Demo seed via real engine | Demo data | PENDING |
| B-3a | GET /payroll/pay-periods/{id}/preview/{employee_id} | F-7b | PENDING |
| B-3b | Own-payslips endpoint | F-7b | PENDING |
| B-4 | Attendance-to-earnings | F-7 | PENDING |

## Important contracts

- `/auth/login` returns `{access_token, refresh_token, token_type, expires_in}` only.
- `/auth/me` returns `{id, username, role, employee_id, permissions[], must_change_password}`.
- Usernames: `normalise_username` strips separators when a digit is present.
- Refresh: CSRF header still missing on client (flagged since F-1a).
- **`new Request(relativeUrl)` throws in jsdom/Node**. All manual requests go through `absoluteUrl()` in `client.ts`.
- Attendance sheet/daily/day/mark_reviewed field shapes assumed and normalised defensively (see `attendance.ts` and `warn` in it). Verified against real backend not yet.
- `GET /attendance/day/{employee_id}/{work_date}` assumed per 2B spec. May differ; if it 404s, F-2b-day-panel-fix replaces `fetchDay` with `fetchPunches` from `/punches`.
- `POST /attendance/mark_reviewed` assumed to return `{reviewed_count, refused_days: [...]}`. May differ; if it 422s or shape doesn't match, one fix bundle adjusts.

## Verified gaps

Only B-2, B-3a, B-3b, B-4 remain.

## Decisions

- Monthly and daily views share the same filter bar. Daily view adds a `date` input.
- Day panel opens as a right Drawer (Mantine). Editing punches not in F-2b — that's F-3.
- Mark reviewed modal is a Mantine Modal; result shown inline with a refused-days table.
- Adjustment markers never appear on the grid, daily list, or day panel (C2). DayPanel has an explicit comment; test asserts `/adjust/i` not present in the day panel.
- Attendance-status chip is a client-side post-filter. Server-side requires backend support (flagged).
- Cursor is forward-only; "first page" and "next page" only.

## Known tool limitation

`apply_bundle.py --frontend` runs Vitest only on files inside the bundle. `--also` files are committed but tests are not re-run on them.

## Next step

F-3a: exceptions queue with type chips and suggested fixes; single adjustment form (outcome, times, reason_code, note-required-for-other); handle `cannot_adjust_own` (403), `day_locked` (409), and error codes with clear messages. Also clean up F-2b's `dailyDate` input (moved into FilterBar for consistency).
