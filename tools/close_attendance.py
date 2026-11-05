"""Close the attendance-work day: append a 'bundles shipped' section to
docs/FRONTEND_STATE.md so the state doc reflects reality."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "docs" / "FRONTEND_STATE.md"
src = P.read_text(encoding="utf-8")

marker = "## Attendance end-to-end (shipped)"
if marker in src:
    print("attendance section already present")
else:
    section = """
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
"""
    P.write_text(src + section, encoding="utf-8")
    print("docs/FRONTEND_STATE.md: attendance section appended")