# Frontend state

## Exceptions queue (F-3a)

### Type filter
- Supported exception types (exact set):
  `missing_out`, `missing_in`, `no_shift_match`, `low_confidence`,
  `absent_expected`, `overtime_unapproved`, `too_long`, `duplicate`,
  `device_clock_gap`, `employee_query`.
- Labels live in `src/lib/strings.ts` under `exceptionTypes`.
- "missing_punch" removed everywhere; do not reintroduce.

### Client-side type filtering
- Filtering applied on the client over loaded items; server supports only
  single-type today. Multi-type filter note shown next to the filter.

### Time handling
- All times constructed and rendered in the **site** timezone, never the
  browser's. `SITE_TIMEZONE = "Africa/Johannesburg"` (pending B-5).
- `buildShiftTimes` treats end earlier than start as next calendar day; the
  AdjustmentForm shows a "+1 day" indicator.
- `toTimeInput` formats ISO -> "HH:mm" in SITE_TIMEZONE (form defaults and
  suggested summary).

### Apply suggestion / resolve
- Confirmation modal before mutation.
- Page-level dismissible `Alert` above the list shows mapped errors
  (`day_locked`, `cannot_adjust_own`, `record_changed`, …) for **every**
  resolve path.
- Busy tracked per-card via `resolvingId`; only the card being resolved is
  loading/disabled.
- On success invalidates `['exceptions']`.
- **B-7 (gap)**: attendance sheet and day-panel invalidation not wired — their
  `queryKey`s live in f007 / AttendanceSheetPage and are not in this bundle.
- **B-8 (gap)**: `ResolveModal` not in this bundle; its resolve path must also
  feed page-level errors and respect per-card busy.

### Employees
- `fetchEmployees` no longer swallows errors; rejects so callers can show an
  error state with retry. Follows `next_cursor` until exhausted (page 500).

### Pagination
- `fetchExceptionsPage(cursor)` returns `{ items, next_cursor }`; list uses
  `useInfiniteQuery` + "Load more" appends items.

### Misc
- Empty state is status-neutral: "No exceptions match the current filters."
- Reason code length validated to max 40 in `AdjustmentForm`.
- `strings.resolve.reasonCodeHint` is neutral ("Describe the reason for this
  change.") — no invented reason codes.

## Pending test fixes (path-blocked)
Two tests in an existing test file (not present in this bundle) fail — test-code
only, not app bugs. Provide the path and the file will be delivered corrected.

1. `"renders the title, exception row, and employee name"`
   - `getByText(/missing out/i)` matches 2 elements (badge + span).
   - Fix: `within(screen.getByTestId("exception-exc1")).getByText(/missing out/i)`
     (or use dedicated testids on badge/span).
2. `"adjustment form rejects 'other' reason with a short note"`
   - `/at least 10 characters/i` matches both the error `Alert` and the
     `Textarea` hint.
   - Fix: `within(dialog).getByRole("alert")` (scope to the alert only).

Review every other `getByText` in that file for badge-label / hint / error-text
ambiguity at the same time.

## Backend requests
- **B-5**: Provide site timezone via API (currently hardcoded).
- **B-6**: Multi-value type filtering on `GET /exceptions`.