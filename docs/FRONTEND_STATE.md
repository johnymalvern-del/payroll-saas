# Frontend state

## F-3a closure (2026-11-03)

- `frontend/src/pages/ExceptionsPage.test.tsx`: 17/17 passing
  (`npx vitest run src/pages/ExceptionsPage.test.tsx --reporter=dot`).
- Both ambiguous `getByText` calls noted in the handoff were already
  scoped with `within(...)` on disk; verified green. No source change
  was needed for F-3a.

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
  `GET /sites?ids=...`) — needed to compute adjustment times in each
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

## F-7 Pay periods (committed)

- `/payroll/pay-periods` renders `PayPeriodsPage` (list + create modal).
- `/payroll/pay-periods/:id` renders `PayPeriodDetailPage` (preview + finalise with ack + reopen + reopen log).
- API module: `frontend/src/api/payPeriods.ts`.
- Strings: `strings.payPeriods`.

### F-7a (api + strings)
- `fetchPayPeriods`, `fetchPayPeriod`, `createPayPeriod`, `previewPayPeriod`, `previewPayPeriodEmployee`, `finalisePayPeriod`, `reopenPayPeriod`, `fetchReopenLog`.
- `PayPeriodsApiError` carries `code`, `status`, `details`.

### F-7b (list page)
- `useInfiniteQuery(["pay_periods", status])` + Load more.
- Status SegmentedControl: all / open / locked.
- Row: period key, status badge, date range, pay date, `Open` button → detail route.
- Create modal: `period_key`, `start_date`, `end_date`, `pay_date`, `cutoff_at`.
  - `cutoff_local` entered as `datetime-local`, converted via `dayjs.tz(..., getSiteTz())` then `.toISOString()`.
  - Frontend validation: required fields, end >= start, pay_date >= end. Backend enforces `period_key_taken`, `invalid_range`, `invalid_pay_date`.
  - Errors map through `mapErrorCode`.

### F-7c (detail page)
- Header: back button, title (`Pay period <key>`), status badge.
- Actions: Preview (disabled when locked), Finalise (disabled when locked), Reopen (disabled when not locked).
- Preview: `POST /payroll/.../preview` → inline table (Employee, Gross, PAYE, Net, Warnings). `unacknowledged_formulas` banner when non-empty.
- Finalise:
  - Modal with `ack_open_exceptions_reason` Textarea.
  - First submit with no ack → backend 409 `open_exceptions_in_period` → modal stays open, `needsAck=true`, error shown, user types reason, submit again.
  - Blank ack while `needsAck` → local validation error.
  - `period_locked` mapped via `strings.payPeriods.errPeriodLocked`.
- Reopen: Modal with required `reason` Textarea; blank submit → local validation error. `later_period_locked` surfaces via `mapErrorCode`.
- Reopen log: shown only for locked periods when entries exist.

### Known limitations
- **Per-employee preview drill-down** (`previewPayPeriodEmployee`) is wired in `payPeriods.ts` but not surfaced in `PayPeriodDetailPage`. Follow-up: row click opens a `PreviewEmployeeDetail` modal or route; test on arrival.
- **No `pay_period` cache invalidation on finalise/reopen beyond `pay_periods` list + reopen log** — the current detail refetch comes from `["pay_period", id]` invalidation. If a payslip view exists later, it will need its own invalidation key.
- **`unacknowledged_formulas` warning is informational only** — no "acknowledge" button; formula acknowledgement lives on the (future) payroll-formulas screen.

## F-8 Audit log (committed)

- `/audit-log` renders `frontend/src/pages/AuditLogPage.tsx` (was PlaceholderPage).
- API module: `frontend/src/api/auditLog.ts`.
- Strings: `strings.auditLog`.

### Page
- Filters (all optional, Apply button, Clear button):
  `occurred_from`, `occurred_to` (date, day bounds), `entity_type`, `entity_id`,
  `action`, `actor_role`, `actor_user_id`, `request_id`, `reason`.
- `occurred_from`/`occurred_to` are converted to ISO with `startOf("day")`/
  `endOf("day")` before send.
- Range notice: reads `occurred_from_applied` / `occurred_to_applied` from the
  first page's response — the backend may widen or clamp the requested range
  (defaults to last 30 days when `occurred_from` is unset). Note is shown in a
  small dim text under the filters.
- List: `Table` with columns Occurred at / Actor role / Action / Entity type /
  Entity id (short) / Request id (short) / View.
- Load more via `useInfiniteQuery`.
- Detail: `Drawer` (right, lg) with all fields, `old_value`/`new_value`
  pretty-printed as JSON in monospace. Fetched lazily via
  `["audit_entry", id]` on View click.
- Filter errors: local `invalid_range` check (From > To) prevents the request;
  server `invalid_range` and `audit_entry_not_found` mapped via
  `mapErrorCode` / specific strings.

### Known limitations
- Times rendered with `dayjs(...).format(...)` — browser tz, not site tz.
  Follow-up to route through `getSiteTz()` (same call as F-1c) once time-tz
  display becomes a global concern.
- Full ID shown only in the drawer; table truncates to 8 chars.
- No action-level drill-down shortcuts (e.g. click `request_id` to filter by
  it) — one click on View opens the drawer with the full value visible.
- No export / CSV.

## Own payslips (committed)

- `/payslips` renders `frontend/src/pages/OwnPayslipsPage.tsx` (was PlaceholderPage).
- API module: `frontend/src/api/ownPayslips.ts`.
- Strings: `strings.payslips`.

### Page
- Auditor role: shows a notice (`payslips-auditor-notice`) and never fetches — matches master brief §6.
- List: `useInfiniteQuery(["my_payslips"])` → `GET /payroll/payslips/me`. Columns: period, pay date, status, gross, net, actions.
- Load more via `next_cursor`.
- Detail: `Drawer` (right, lg) driven by `GET /payroll/payslips/me/{id}`; shows gross → net breakdown + revision + computed_at. Uses the row's `period_key` for the title (the payslip payload has only `pay_period_id`).
- PDF: `GET /payroll/payslips/me/{id}/pdf` → blob URL + anchor click; filename "payslip.pdf". Errors surface in a page-level dismissible Alert (`payslips-pdf-error`). Audited backend-side (`payslip.pdf_download_by_other` when non-owner; owner download is silent).
- Errors mapped via `mapErrorCode`; `forbidden` → auditor notice text; `no_employee_record` → list error text.

### Known limitations
- Drawer title uses the row's `period_key` (passed via state) — a hard reload of a deep link to a payslip (no such route today) would need a `fetchPayPeriod` call.
- Times shown with `dayjs(...).format(...)` (browser tz); follow-up to route through `getSiteTz()` as part of a global display pass.
- No bulk PDF download; per-row only.
- Employee-facing screen shows `status` (`current` | `superseded`) verbatim, uncoloured; no status-specific messaging for `superseded` beyond the raw value.

## Attendance end-to-end (shipped)

Bundles shipped against the "attendance usable today" goal:

### Bundle 1 — Clock-in + Devices + tz plumbing
- `/clock-in` (ClockInPage): employee-code lookup via
  `GET /employees?employee_code=`, camera capture → `photo_base64`,
  `POST /punches` with `X-Device-Key` header.
- Device key in `localStorage` (key `payroll.device_key`, wrapped in
  try/catch); "Reset this device" clears it.
- `/setup/devices` (DevicesPage): list, create (key shown once via
  `DeviceCreateOut.api_key`), rotate key via
  `POST /devices/{id}/rotate-key`.
- `useMe` already applies `applyMeSiteTz` → `setSiteTz`; no change
  required.

### Bundle 2 — Setup screens
- `/setup` is a `SetupLayout` with tabs: Sites, Branches, Departments,
  Shifts, Work Patterns, Public Holidays, Devices.
- Each tab: list + create (Sites also timezone; Shifts also inline rate
  rules modal; Work Patterns also 7-day expected grid; Public Holidays
  also deactivate + CLI note for country-level rows).
- EmployeesPage `EmployeeForm` already had branch/site/department/
  manager/work-pattern/default-shift pickers on disk — B8, B9, B10
  confirmed closed without further change.

### Bundle 3 — CSV export
- `/attendance` header has "Export CSV" (`attendance-export-csv`),
  long-format rows from `sheet.data.items`, built by
  `lib/csv.ts::toCsv` (RFC 4180-safe) + `downloadCsv` (blob URL).

### Already on disk (verified, no bundle needed)
- F-1 `/auth/me` `default_timezone` → `setSiteTz` → `getSiteTz()`.
  `DEFAULT_SITE_TZ` only appears in `lib/config.ts` and test files.
- Reason-code `Select` in `AdjustmentsPage` (fed by
  `GET /attendance/reason-codes`, `requires_note` gating).

### Test counts
- 7 new frontend test files this work: ClockInPage (5),
  DevicesPage (2), setup/* (6), csv.test.ts (6).
- Regression gates kept green: ExceptionsPage 17/17, EmployeesPage
  11/11, AttendanceSheetPage unchanged.

### Open items (not today)
- B13 country calendar CSV load — CLI-only by design (§10).
- EmployeeForm "date-scoped" work-pattern history via
  `/employees/{id}/work-patterns` — direct `work_pattern_id` field
  is live; history UI is deferred.
- Real ZA public holidays 2026–2027 — awaiting user CSV (§10).

## Visual polish P1 (shipped)

### Theme (single source of colours, fonts, radius, shadows, spacing)
- `frontend/src/theme.ts` — Mantine `createTheme`. Light-only this pass
  (`defaultColorScheme="light"` in `main.tsx`).
- Palettes: `navy` (primary, deep #0B3D5C), `accent` (warm #C45F22),
  `approved` (green), `pending` (amber), `problem` (red). `gray`
  inherited from Mantine defaults for `inactive`.
- Fonts: Inter (system stack fallback; no npm font package added).
- Radius: `md` (12px) global. Shadows: `sm` on Card, `md` on Modal.
- `theme/components` overrides: `Button`, `Paper`, `Card`, `Badge`,
  `Modal`, `Alert`, `Table` (uppercase th, `F7F8FA` background, no
  stripes, hover-on).
- `frontend/src/theme/colors.ts` — semantic colour aliases used by
  every page (`colors.approved`, `colors.pending`, `colors.problem`,
  `colors.inactive`, `colors.info`, `colors.warning`, `colors.accent`).
  No page writes a literal colour name.
- Previous `theme.ts` preserved as `theme.backup.ts` (unused; can be
  deleted with `git rm frontend/src/theme.backup.ts` if not needed).

### App shell
- `frontend/src/shell/AppShell.tsx` — Mantine `AppShell` with:
  - Left `Navbar` (248px), grouped by section (Attendance / People /
    Payroll / Setup / Audit), icon + label per item, active-state
    styling via theme tokens.
  - Header (56px) with brand text + user menu (role label + logout).
  - Mobile: hamburger toggles `Navbar`.
- `frontend/src/shell/nav.ts` — new grouped `buildNav` returns
  `NavGroup[]` (`label`, `items[]`). Same permission gates as before;
  Home gated on `self_view`; Clock-in gated on `attendance_view`;
  Payslips gated on `payslip_view`.
- `frontend/src/shell/nav.test.ts` — rewritten (6 tests, grouped shape).

### Layout primitives (available for page adoption in P2/P3)
- `components/layout/Icon.tsx` — 12 inline SVG icons (no npm
  dependency added).
- `components/layout/PageHeader.tsx` — title + optional subtitle +
  actions slot.
- `components/layout/EmptyState.tsx` — centered dimmed message.
- `components/layout/TableSkeleton.tsx` — header + row skeletons.

### Colour sweep
- 24 `*.tsx` files: literal `color="red|green|orange|yellow|blue|gray"`
  replaced with `color={colors.X}`. `import { colors } from
  "<rel>/theme/colors"` added to each.

### Verification
- tsc clean.
- 120/120 vitest green (23 files).
- Browser check pending user confirmation.

### Notes / deferred
- Dark mode is a follow-up pass (palette tuned for light).
- Tenant name in header: `UserMeOut` has no tenant-name field.
  Header shows "Payroll" (appName). Real tenant name needs a `/tenant`
  endpoint (backend gap, out of P1 scope).
- `PageHeader` adoption in individual pages is a P2/P3 concern — the
  theme overrides apply without markup changes.

## F-9 Salary structures (M3 Stage F, committed)

Three pages + three API modules. Routes: `/payroll/salary-structures` (list),
`/payroll/salary-structures/:groupId` (detail), `/payroll/employee-payroll`
and `/payroll/employee-payroll/:employeeId` (index / detail). Nav: two
`pay_rate_view`-gated items under People ("Employee payroll") and Payroll
("Salary structures"); `nav.test.ts` expected path lists refreshed for hr
and auditor.

API modules: `salaryStructures.ts` (7 functions, `StructureApiError`),
`payrollTypes.ts` (`fetchEarningTypes`, `fetchDeductionTypes`),
`salaryAssignments.ts` (7 functions, `AssignmentApiError`).

### F-9a SalaryStructuresPage
List current structures; create modal (name, description, pay_basis,
base_rate, dynamic components). Earning component requires exactly one of
amount/rate; deduction requires amount. Deactivate per row via
`window.confirm`. Earning/deduction dropdowns filter `is_system`,
`BASE_MONTHLY`, `is_active=false`. 10 tests.

### F-9b SalaryStructureDetailPage
Header (name, version, current, active badges), component table, version
history, Edit modal (name, description, base_rate — submits version_number +
row_version), Deactivate. Component editing is deferred. 10 tests.

### F-9c EmployeePayrollPage
Index (employee list, each links to detail). Detail (assignment history,
submit form: structure select, effective date, "Check overlaps"). Collision
pre-check renders manual rows as checkboxes (`requires_override` only
selectable) plus structure-owned rows in a blue notice. Submit builds
`override_manual_ids: [{kind, id}]`. 8 tests.

### Known limitations
- No approve / reject / cancel UI in `EmployeePayrollPage`. API functions
  exist (`approveAssignment`, `rejectAssignment`, `cancelAssignment`);
  F-9d will surface them.
- Edit modal does not touch components.
- No list pagination on salary-structures / assignments.
- Strings inlined per page — M3 pages do not consume `strings.ts`.
- `check-collisions` submits with empty `override_manual_ids`; user toggles
  overrides after seeing candidates.
- Individual change-request children (`assignment_id IS NOT NULL`) not
  filtered from `ChangeRequestsPage` — backend guard refuses individual
  actions. F-9e.