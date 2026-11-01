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
- `AdjustmentForm`: `toTimeInput` formats form defaults in site tz;
  night shift (`timeOut < timeIn`) emits `time_out` as next calendar day
  with a `+1 day` indicator; `reason_code` max 40 validated.
- `suggestionSummary` formats `Suggested: worked HH:mm–HH:mm` in site tz.

### Resolve / apply suggestion (single)
- Direct apply: `window.confirm`; page-level dismissible `Alert`
  (`data-testid="direct-error"`) shows `mapErrorCode`.
- Per-card busy: `resolve.isPending && resolve.variables?.id === row.id`.
- Success: `invalidateQueries(["exceptions"])` + `["attendance"]` (prefix).

### Pagination
- `useInfiniteQuery` on `["exceptions", status]`; `limit=100`; "Load more"
  (`data-testid="exceptions-load-more"`) only when `hasNextPage`.

### Bulk resolve (F-3b, partial)
- Bulk mode toggle on the page (`data-testid="exceptions-bulk-toggle"`).
- Per-card checkbox (`exception-select-{id}`) via `ExceptionCard.selectable`.
- Actions: `apply_suggestion` | `dismiss` (bulk custom is per-row via the
  existing single resolve modal; bulk custom with per-row form is not
  built).
- Flow: **Dry run** → POST `bulk_resolve` without `token` → shows per-row
  result panel (`exceptions-bulk-results`); if every row is OK the
  Confirm button enables → Modal (`exceptions-bulk-confirm-modal`) →
  POST `bulk_resolve` with the dry-run token. Success invalidates
  `["exceptions"]` and `["attendance"]`.
- Mapped errors: `token_mismatch` → "re-run the dry run";
  `bulk_validation_failed` → page alert + re-render dry-run results from
  `err.details.results`; `batch_failed` → "nothing was applied".
  Per-row `error_code` values render inside the results panel via
  `mapBulkError` (falls back to `mapErrorCode` for standard codes like
  `day_locked`, `cannot_adjust_own`, `note_required`).
- All-or-nothing is enforced by the backend; the UI never partially
  applies.
- Bulk uses the same `BulkApiError` class for status + `details` so the
  page can surface stale-token and validation-failed details.

## Bulk adjust + revert (F-3b, pending)
- `POST /api/v1/attendance/adjustments/bulk` exists (dry-run + token, same
  pattern as bulk resolve) but the exact `BulkAdjustIn` / item-out schema
  is not yet known. **B-9**.
- `POST /api/v1/attendance/adjustments` accepts `outcome: "revert"`
  (frontend `AdjustmentCreateRequest` already includes it); revert UI
  shares the same page as bulk adjust (replacement of the
  `/attendance/adjustments` PlaceholderPage) and needs the route file to
  wire. **B-10**.
- Both are deferred until B-9 and B-10 land so no fields or routes are
  invented.

## Closed gaps
- **B-7 (closed)**: `["attendance"]` prefix invalidation covers the sheet,
  daily list, and open day panel after resolve.
- **B-8 (closed)**: `ResolveModal` renders `serverError` as an `Alert`
  inside the modal; direct-apply errors flow through the same page state.

## Open backend requests
- **B-5**: site timezone from API — partially satisfied by
  `GET /api/v1/company` → `default_timezone`; per-employee site tz still
  needed for full compliance (**B-11**).
- **B-6**: multi-value type filter on `GET /attendance/exceptions`.
- **B-9**: full `BulkAdjustIn` / `BulkAdjustItemIn` / `BulkAdjustItemOut`
  / `BulkAdjustOut` schema so bulk-adjust UI can be built without guesses.
- **B-10**: frontend route file (App.tsx / routes.tsx) so
  `/attendance/adjustments` PlaceholderPage can be replaced with the real
  bulk-adjust + revert page.
- **B-11**: per-employee site timezone on list endpoints or bulk
  `GET /sites?ids=…`.