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
- `ResolveModal` already receives `serverError` from the page and renders
  it as a Mantine `Alert` (role="alert") inside the modal — the modal path
  surfaces the same errors.
- Busy state is per card: `busy = resolve.isPending && resolve.variables?.id === row.id`.
- On success: `invalidateQueries(["exceptions"])` **and**
  `invalidateQueries(["attendance"])` (prefix) so the attendance sheet,
  daily list, and the open day panel all refetch. See B-7 below.

### Pagination
- `useInfiniteQuery` with `initialPageParam: null`,
  `getNextPageParam: (last) => last.next_cursor ?? undefined`,
  `limit=PAGE_SIZE (100)`.
- "Load more" (`data-testid="exceptions-load-more"`) only when
  `hasNextPage`. Test asserts append on `cursor=abc`.
- Employee list already pages via `next_cursor` with a 20-page safety cap.

### Reason code
- Max 40 chars, validated before `times required` / `other note`.
- Hint neutral: "Describe the reason for this change."

### Empty state
- Status-neutral: "No exceptions match the current filters."

## Closed gaps
- **B-7 (closed in f010b)**: `AttendanceSheetPage` uses
  `queryKey: ["attendance", "sheet", …]` and `["attendance", "daily", …]`,
  and the day panel is under the same `["attendance"]` prefix; a single
  `invalidateQueries({ queryKey: ["attendance"] })` in `onSuccess` covers
  all three. No key was invented.
- **B-8 (closed in f010b)**: `ResolveModal` already takes `serverError` as
  a prop and renders it as a Mantine `Alert` inside the modal. The page
  passes `serverError={serverError}`. Modal path shows mapped errors.

## Open backend requests
- **B-5**: Provide site timezone via API (currently `DEFAULT_SITE_TZ`
  hardcoded to `Africa/Johannesburg`).
- **B-6**: Multi-value type filtering on `GET /attendance/exceptions`
  (`type=a&type=b` or `type=a,b`) so the client-side filter note can go.

## Next: F-3b (pending)
Bulk adjust (dry run + confirm token), bulk resolve, revert. Awaiting the
trimmed OpenAPI to avoid inventing endpoints, fields, or token semantics.