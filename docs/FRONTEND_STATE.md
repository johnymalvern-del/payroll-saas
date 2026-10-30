# Frontend State

Read this first when opening a new chat. Updated at the end of each phase.

## Phase

F-2a — attendance sheet with filters and monthly grid. Root cause of the sheet test failures found and fixed: `new Request("/path")` throws in jsdom/Node because Request requires absolute URLs. All manual request construction now goes through `absoluteUrl()` from `client.ts`. This bug would also have broken the app in a real browser.

## Bundles done

F-0a, F-0b + f002-fix, F-1a + f003-fix, B-1 + B-1-fix-2, F-1b + f004-fix + f004-fix2, F-2a + f005-fix + f005-fix2 + f005-fix3 + f005-fix4 (this bundle).

## Bundle plan (13 frontend bundles remaining)

F-2a ✓ | F-2b | F-3a, F-3b | F-4a, F-4b | F-5a, F-5b | F-6 | F-8 | F-7a, F-7b (waits for B-4).

## Backend requests

| # | Request | Blocks | Status |
|---|---|---|---|
| B-1 | GET /auth/me | F-1b | DELIVERED |
| B-2 | Demo seed via real engine | Demo data | PENDING |
| B-3a | GET /payroll/pay-periods/{id}/preview/{employee_id} | F-7b | PENDING |
| B-3b | Own-payslips endpoint | F-7b | PENDING |
| B-4 | Attendance-to-earnings | F-7 | PENDING |

## Important contracts

- `/auth/login` returns `{access_token, refresh_token, token_type, expires_in}` only. No `must_change_password`. UI uses `/auth/me`.
- `/auth/me` returns `{id, username, role, employee_id, permissions[], must_change_password}`.
- Usernames: `normalise_username` strips separators when a digit is present. Use `paone` not `pa-1`.
- Refresh: backend uses `csrf_token` cookie + `csrf_protection` dependency. **Client does not yet send the CSRF header.** Refresh will 403 until fixed. Flagged.
- **`new Request(relativeUrl)` throws in jsdom and Node >=18.** All manual requests go through `absoluteUrl()` in `client.ts`. `openapi-fetch` receives an absolute baseURL too. Never construct a bare relative Request again.
- `wrappedFetch(new Request(absoluteUrl(...)))` is the correct pattern for any request outside the openapi-fetch client.

## Verified gaps

Only B-2, B-3a, B-3b, B-4 remain. Sheet response field names not verified against a live backend (`warnShapeMismatch` in `attendance.ts` prints them if the shape differs on first live run).

## Decisions

- Attendance sheet uses `wrappedFetch` + manual type cast (not `api.GET`) until `npm run api:types` is run against a live backend. When the schema is generated, F-2a's `api/attendance.ts` types become authoritative.
- Attendance status chip is a client-side post-filter over the loaded page.
- Employee-status filter is `includeTerminated` only.
- Cell tooltip surfaces minutes, flags, open exception count, locked, reviewed — colour is never the only signal.
- Pagination: "first page" and "next page"; cursor is forward-only.
- No row virtualisation yet.
- No day panel yet (F-2b).

## Known tool limitation

`apply_bundle.py --frontend` runs Vitest only on files written **inside the bundle**, not on `--also` files. Consequence: if you change a source file and the test that covers it was already committed, you must either include the test file in the bundle or run `npx vitest run <file>` manually. This caught us on F-1b and again on F-2a. Fix candidate for a later tool revision: also run tests that import changed source files (backend `find_dependent_tests` logic ported to TS).

## Next step

F-2b: day panel (open a cell, fetch `GET /attendance/day/{employee_id}/{work_date}`), daily list view, bulk `mark clean days reviewed` with refused-days table. Requires B-2 for realistic data to exercise the flow.
