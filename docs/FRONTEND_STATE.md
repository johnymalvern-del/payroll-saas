# Frontend state

## Exceptions queue (F-3a)

### Type filter
- Supported exception types (exact set, in `EXCEPTION_TYPE_ORDER`):
  `missing_out`, `missing_in`, `no_shift_match`, `low_confidence`,
  `absent_expected`, `overtime_unapproved`, `too_long`, `duplicate`,
  `device_clock_gap`, `employee_query`.
- "missing_punch" removed everywhere.

### Client-side type filtering
- `MultiSelect` on the page; `items = rawItems.filter(...)` on the loaded
  pages. Server supports only single `type=` today (**B-6**).

### Resolve / apply suggestion
- Direct apply: `window.confirm`; page-level dismissible `Alert`
  (`direct-error`); per-card busy; success invalidates
  `["exceptions"]` + `["attendance"]`.

### Bulk resolve (F-3b)
- Bulk mode toggle on `ExceptionsPage`; per-card checkbox via
  `ExceptionCard.selectable`.
- Actions: `apply_suggestion` | `dismiss`. Dry-run → per-row results →
  confirm modal → POST with dry-run token. Mapped errors via
  `mapBulkError` (`token_mismatch` → "re-run the dry run",
  `bulk_validation_failed` → page alert + re-render from
  `err.details.results`, `batch_failed` → "nothing was applied").

### Pagination
- `useInfiniteQuery` on `["exceptions", status]`; "Load more" follows
  `next_cursor`.

## Adjustments page (F-3b, new)

### Route
- `/attendance/adjustments` renders `AdjustmentsPage` (was
  `PlaceholderPage`). `App.tsx` imports `AdjustmentsPage` from
  `./pages/AdjustmentsPage`.

### Form fields (bulk)
- Outcome: `worked | leave | sick | absent | day_off | revert`.
  "revert" is a first-class outcome (`ADJUSTMENT_OUTCOMES` now
  includes it).
- Time in / time out only when outcome = `worked`; HH:mm text inputs,
  constructed via `dayjs.tz(date + "T" + hhmm, DEFAULT_SITE_TZ)`;
  night-shift rollover (`time_out <= time_in` → `+1 day`).
- From date, To date (inclusive). Dates are local ISO `YYYY-MM-DD`.
- Employees: `MultiSelect` fed by `fetchEmployees` (already follows
  `next_cursor`, rejects on error).
- Reason code: free text, 1-40 chars. Note: optional; required only
  when reason = `other` (10+ chars) — matches backend validator.
- Item list = (selected employees) × (each date in range).
  Capped at 200 rows per `BulkAdjustIn.items.max_length`; over-cap
  shows a yellow alert and disables dry-run.

### Flow
1. Fill in inputs → live row count.
2. **Dry run** → `POST /api/v1/attendance/adjustments/bulk` with
   `{items}` (no token). Renders per-row results
   (`adjustments-bulk-row-{i}`). Confirm only enables when every row
   is `ok`.
3. **Confirm batch** → modal (`adjustments-bulk-confirm-modal`) →
   POST same items + `token` from dry-run. On success shows applied
   count and invalidates `["attendance"]` + `["exceptions"]`.
4. On `bulk_validation_failed` during confirm, the page reconstructs
   the dry-run result panel from `err.results` — no extra call.
5. On `token_mismatch` the mapped error says "Re-run the dry run".

### Revert
- Choosing outcome = `revert` produces items with
  `outcome: "revert", time_in: null, time_out: null`. Same dry-run +
  confirm + mapped errors. Matches `AdjustmentCreateIn` / `BulkAdjustItemIn`
  (`revert` is a member of `_OUTCOMES`; backend restores punch computation).

### Error mapping
`mapBulkAdjustError` handles the three bulk error codes
(`bulk_validation_failed`, `token_mismatch`, `batch_failed`) and
otherwise delegates to `mapErrorCode` (so `day_locked`,
`cannot_adjust_own`, `invalid_reason_code`, `note_required`,
`record_not_found` all map through their normal strings).

## Gaps / backend requests
- **B-5**: site timezone via API — currently `DEFAULT_SITE_TZ`
  (`Africa/Johannesburg`) in `frontend/src/lib/config.ts`.
- **B-6**: multi-value type filter on `GET /attendance/exceptions`.
- **B-11**: per-employee site timezone on list endpoints (or
  `GET /sites?ids=…`) — needed to compute adjustment times in each
  employee's site tz rather than a single constant.
- **B-12**: `GET /attendance/adjustments/reason-codes` (or embed the
  current allowed list in some settings response) so the reason_code
  field can be a `Select` instead of free text. Backend enforces the
  list via `_validate_reason`; today we can only surface that in the
  dry-run per-row error.

## Closed gaps
- **B-7**: `["attendance"]` prefix invalidation covers sheet/daily/day
  panel after resolve or bulk adjust.
- **B-8**: `ResolveModal` surfaces `serverError`.
- **B-9**: `BulkAdjustIn` / `BulkAdjustItemIn` / `BulkAdjustItemOut` /
  `BulkAdjustOut` read from `adjustments_schemas.py` and implemented.
- **B-10**: `/attendance/adjustments` placeholder replaced with
  `AdjustmentsPage`; route unchanged.