# Frontend state

## Exceptions queue (F-3a)

### Type filter
- Supported exception types (exact set, in `EXCEPTION_TYPE_ORDER`):
  `missing_out`, `missing_in`, `no_shift_match`, `low_confidence`,
  `absent_expected`, `overtime_unapproved`, `too_long`, `duplicate`,
  `device_clock_gap`, `employee_query`.
- Labels in `EXCEPTION_TYPE_LABELS` (frontend/src/lib/strings.ts).
- "missing_punch" removed everywhere (types, hints, fixtures).

### Client-side type filtering
- `MultiSelect` on the page; `items = rawItems.filter(...)` on the loaded
  pages. Server supports only single `type=` today. Filtering stays
  client-side until **B-6** lands.

### Time handling
- `DEFAULT_SITE_TZ = "Africa/Johannesburg"` (`frontend/src/lib/config.ts`).
- `AdjustmentForm`:
  - `toTimeInput` formats form defaults via `dayjs(...).tz(DEFAULT_SITE_TZ)`.
  - Night shift: if `timeOut < timeIn` (HH:mm string compare), `time_out`
    is `dayjs.tz(...).add(1, "day")`; a `+1 day` indicator
    (`data-testid="adj-next-day"`) is shown. Both computed in site tz.
  - Equal times are rejected (`timeOrder`).
- `suggestionSummary` formats `Suggested: worked HH:mm–HH:mm` in site tz.
- New tests in `AdjustmentForm.test.tsx` round-trip through
  `dayjs(v.time_in).tz(DEFAULT_SITE_TZ)` so they pass on any machine tz.

### Resolve / apply suggestion
- Direct apply: confirmation via `window.confirm`; on failure the page-level
  dismissible `Alert` (`data-testid="direct-error"`) shows `mapErrorCode`.
  Covers `day_locked`, `cannot_adjust_own`, `record_changed`, …
- Busy state is per card: `busy = resolve.isPending && resolve.variables?.id === row.id`.
- On success: `invalidateQueries(["exceptions"])`.

### Pagination
- `useInfiniteQuery` with `initialPageParam: null`,
  `getNextPageParam: (last) => last.next_cursor ?? undefined`,
  `limit=PAGE_SIZE (100)`.
- "Load more" button (`data-testid="exceptions-load-more"`) only when
  `hasNextPage`. New test asserts append on `cursor=abc`.
- Employee list already pages via `next_cursor` with a 20-page safety cap.

### Reason code
- Max 40 chars, validated before `times required` / `other note`, so it
  fails fast. Hint is neutral: "Describe the reason for this change."

### Empty state
- Status-neutral: "No exceptions match the current filters." (not
  "No open exceptions").

## Gaps / backend requests
- **B-5**: Provide site timezone via API (currently `DEFAULT_SITE_TZ`
  hardcoded to `Africa/Johannesburg`).
- **B-6**: Multi-value type filtering on `GET /attendance/exceptions`
  (`type=a&type=b` or `type=a,b`) so the client-side filter note can go.
- **B-7 (frontend gap)**: attendance sheet + day-panel invalidation after
  resolve is **not wired** — query keys live in `AttendanceSheetPage` and
  are not in this bundle. `TODO(B-7)` marker is in `ExceptionsPage.onSuccess`.
  Once the keys are known: add them next to `invalidateQueries(["exceptions"])`.
- **B-8 (frontend gap)**: `ResolveModal` must feed failures into the same
  `setServerError` callback that the page already uses for direct apply
  (already wired here via `onResolve` — verify modal doesn't swallow errors
  on submit; if it does, propagate).

## Backend requests
- **B-5**: site timezone from API.
- **B-6**: multi-value type filter on exceptions list.