# Payroll SaaS - Project State

Last updated: close of Chapter 2C (Attendance work surface).

This file is the handoff for a new chat. It is not a design document; it is
where we are, what was decided, what comes next. Where this file and the
master brief conflict, the brief wins except where a decision below records
that the user overrode it.

## Repository and toolchain

- Root: `C:\xampp\htdocs\Payroll`
- Backend package: `backend/`; venv at `C:\xampp\htdocs\Payroll\.venv`
- Scripts: `scripts\run_tests.ps1`, `scripts\setup_windows.ps1`, `scripts\dev.ps1`
- Tests at close of 2A: **569 passed** (0 failed, 2 warnings)
- Stack: Python 3.12, FastAPI, SQLAlchemy 2.x (typed, sync), psycopg 3,
  Alembic, Pydantic v2, PostgreSQL 16 native on Windows. No Docker.
- Control DB `payroll_control`; one DB per tenant; tenant via `X-Tenant-Slug`
  in development.
- Auth: JWT access (15 min) + rotating refresh (30 days), argon2id,
  forced first-login password change, per-IP rate limit.
- Cursor envelope on every list: `{"items": [...], "next_cursor": "..."}`,
  default limit 100, max 500, optional `?include_total=true`.
- Concurrency: `row_version` on PATCH; stale -> 409 `record_changed`.
- Audit: append-only `audit_log` (REVOKE + trigger), every mutation writes a
  redacted row via `redact_for_audit`.
- Soft delete via `is_active`; `DELETE` returns 409 `<thing>_in_use` when
  referenced.
- TenantCrypto is per-request on `TenantDep.crypto`. `Employee.national_id`
  and `bank_account_number` are encrypted at rest and masked on read.
- Test-side rate-limiter bypass in `tests/conftest.py`; the real limiter is
  still active for `test_auth_endpoints.py` and `test_rate_limiter.py`.

## Delivery mechanism (fixed at close of 2A)

The single biggest source of wasted effort in 2A was delivery, not code.
Multi-line scripts pasted into the terminal were the recurring failure.
From 2B onward:

- Every deliverable is a full `.py` or `.ps1` file **saved in VS Code**. The
  only typed terminal command is one `python <path>` or `powershell -File
  <path>` invocation, plus the final `run_tests.ps1`.
- Terminal is for short commands only (one line, no multi-line content).
- Every `.py` that patches other files uses `[System.IO.File]::WriteAllText`
  with an absolute path, or `pathlib.Path(...).write_text(...)`. No relative
  paths in .NET File APIs, no `python -c` with `''` escaping.
- Every file ends with `
## Chapter 4 closed (payroll engine)

Chapter 4 delivered. Payroll engine wired end to end:
  - Control-DB statutory tables via scripts/load_statutory_tables.ps1 (F1)
  - Eleven pay tables + three employee columns via ten_0017
  - payroll_settings (ten_0018) + formula_acks (ten_0019)
  - payroll_change_request (ten_0020) - F3 change-request flow
  - TaxEngine v1 (regular-earnings only, per F5)
  - UIF ceiling-first, SDL tenant gate, retirement 11F cap
  - 8-step pipeline with net-pay floor and F7 legal-order refusal
  - Pay periods: preview persists per F4, finalise, reopen
  - Payslip endpoints + minimal PDF renderer
  - Hand-worked payslip case framework (tests/data/payslip_cases/)
  - apply_bundle.py now runs tests for importers of changed source files,
    and its do_commit skips gitignored files (fixes the recurring
    scripts/*.py staging failure)

### Open items carried into Chapter 5+
- apply_import_row_fields not wired into import_employees.py
- provision_tenant does not auto-seed system earning types
- Payslip PDF returns bytes; StorageDep integration deferred
- per_hour earning types refused (calc_method_unsupported) until
  attendance-to-earnings integration lands
- Bank file, journals, EMP201 / EMP501 / IRP5 / IT3(a) exports
- Photo retention policy, HMAC on punch payloads, daily sweep scheduler
- reviewed_at not cleared when only an exception appears (from 2C)

### Next

Chapter 5 (payroll outputs and statutory exports). SPEC-only first.

# END OF FILE` (Python/PS) and the file-writing
  script verifies that marker as its last non-empty line.
- Register new routers in `app/api/v1/__init__.py` in the same commit that
  creates the router. Two routers shipped unregistered in 2A because that
  step was deferred.

## Milestones

### Done (committed)

- 1C.4 company GET/PATCH with row_version
- 1C.4.1 branch scope helpers
- 1C.5 branches CRUD
- 1C.6 sites CRUD; 1C.6.1/1C.6.2 rate-limiter test scoping
- 1C.7 departments CRUD
- 1C.8 employees CRUD with crypto at rest
- 1C.9 users CRUD, user_scope, one active user per employee
- 1C.10 pay-rate-change approval flow, PAY_RATE_VIEW
- 1C.11 employee import (CSV, dry-run + token gate, opening rates)
- 1C.12 audit-log read API (read-audited)
- **2A attendance foundation** (this commit)

### Next

- **2B attendance calculation**: session building, shift detection, day
  build (rounding, grace, breaks, overtime tiers, midnight split, day
  types), rate lookup via `find_rule_for_minute`, expected days and
  absences, public-holiday-not-worked, recompute.
- **2C attendance work surface**: exceptions queue, single + bulk
  adjustments, attendance sheet (monthly grid + daily list API).
- Then Chapter 3 (requests), Chapter 4 (payroll), Chapter 5 (reports +
  POPIA), Chapter 6 (devices), Chapter 1D (frontend, not started, 0%).

## What 2A delivered

Migration 0012: 8 tables + a `device` ALTER. Punch is append-only via
REVOKE UPDATE/DELETE plus a BEFORE UPDATE OR DELETE trigger. Grants for the
7 new tables applied at the end of 0012.

Models in `app/db/tenant/models/attendance.py`: Shift, ShiftRateRule,
WorkPattern (with `days` relationship), WorkPatternDay, PublicHolidayTenant,
Punch, EmployeeWorkPattern. Device stays in `devices.py`; 0012 adds
`row_version` and converts the non-unique index to `uq_device_api_key_hash`.
`tests/test_schema_drift.py` compares every non-control table's model
columns against `information_schema.columns` on the tenant DB.

Endpoints, all registered in `app/api/v1/__init__.py`:
- `/shifts` (5), `/shifts/{shift_id}/rate-rules` (3)
- `/work-patterns` (5; days nested, replaced wholesale on PATCH)
- `/employees/{employee_id}/work-patterns` (3, effective-dated history)
- `/public-holidays` (4, future-dated delete only)
- `/devices` (5 + `/devices/{id}/rotate-key`)
- `/punches` (GET list, POST single, POST `/batch`, GET `/{punch_id}`)

Punch pure functions in `app/api/v1/punch_service.py` (no DB, no HTTP):
- A2 timing: effective_time = device_time - offset; a live punch resolves
  to server time, an offline batch punch preserves its recorded wall clock.
- A3 idempotency: canonical_payload_hash over identity fields only.
- A6: photo magic bytes (JPEG/PNG) + 300 KB cap; raw_payload template-key
  rejection and 8 KB cap.
- A4 classifiers: future_time, clock_gap, low_confidence, liveness_failed.

### Decisions inside 2A (recorded)

- D1 SHIFT_CONFIGURE (payroll_admin only) for shifts, rate rules, work
  patterns, public holidays, devices.
- D2 payroll_admin creates a device and receives the raw key once.
- D3 device auth via X-Device-Key; HMAC over punch payloads deferred to
  Phase 6.
- D6 shift-detection tiebreak: nearest start time, tie-break lowest id.
- D7 day_index = (D - anchor_date).days % cycle_length_days.
- A1 device keys via secrets.token_hex(32); SHA-256 hex (not argon2, because
  argon2 is salted and cannot be looked up by); hmac.compare_digest; failed
  attempts rate-limited by IP; non-active device -> 403 device_inactive.
- A2 effective_time computed server-side; device_time, device_now_at_send,
  offset_ms, effective_time all stored.
- A3 client_punch_id unique per (device_id, client_punch_id); same pair +
  same payload_hash returns the stored row; different hash -> 409
  punch_uuid_reused.
- A4 punch.flags JSONB list; status immutable.
- A5 unknown employee -> 422; terminated -> rejected + employee_not_active
  flag; code-only policy per device; missing photo when required -> 400;
  roaming flagged site_mismatch, not rejected.
- A6 photo byte-level validation; raw_payload template-key scan.
- A7 rate-rule tiers contiguous from 1, tier_up_to_minutes strictly
  increasing, one open-ended top tier; overlap of effective periods for the
  same key rejected; same-period siblings are the rule set being extended,
  so the overlap check excludes them.
- A8 delete rules: hard-delete only when unreferenced; past-dated rate
  rules and public holidays cannot be deleted, only ended with effective_to
  or is_active=false.
- A9 employee_work_pattern effective-dated history. Employee.work_pattern_id
  and default_shift_id deprecated until after 2C.
- A10 ATTENDANCE_VIEW granted to employee, manager, hr, payroll_admin per
  section 6. **Auditor NOT granted** (section 6 gives auditor no attendance
  row). One line to flip if intended differently.
- A11 is_working_day_override = true means country-holiday-overridden-
  to-working-day; false means tenant-declared holiday on top of the
  country calendar. 2B must raise setup_error holiday_calendar_missing when
  the year has no holiday data.
- A12 test_schema_drift.py skips the six control-DB tables by name and
  compares every other table's model columns against information_schema.

### Migration 0012 history

As authored, 0012 recreated `device` (which existed from 0001) and the
tenant migration failed with DuplicateTable. Fixed by replacing CREATE
TABLE device with ALTER TABLE ADD COLUMN row_version and converting
ix_device_api_key_hash to UNIQUE. 0001's device defaults kept:
site_id ondelete=CASCADE, status DEFAULT 'offline', api_key_hash VARCHAR(255).
Endpoint sets status='active' explicitly at create.

### Production bug fixed during 2A

`app/core/errors.py`'s validation_exception_handler was returning Pydantic's
`exc.errors()` raw, which contains `ctx.error` as a ValueError instance and
cannot be JSON-serialised. Any endpoint with a custom @field_validator
raising ValueError returned 500 instead of 422. Fixed: strip `ctx` from each
error dict, keep `msg`. Exposed by shift create with an invalid enum.

### 2A stats

- Scripts delivered: ~20 groups over many sessions. Delivery failures (paste
  into terminal, not saved to disk) were the majority of failures.
- Actual code defects caught: .NET ReadAllText(relative) CWD issue;
  control-DB tables in the drift test; backslash \x literals becoming ASCII
  in two files; overlap check rejecting same-period siblings; Session.get()
  identity-map after delete; WorkPattern.days relationship missing; three
  unregistered routers; errors.py ctx ValueError JSON issue.
- Decisions asked from the user: 2 (A10 shape, auditor scope). Everything
  else was in the SPEC.

## Open items for 2B / later phases

- 5 MB batch body cap (A6) not yet enforced. Middleware recommended.
- Photo happy path not tested (would write to StorageDep; needs a test
  override in conftest, not production code).
- `sites.py site_in_use` counts employees only. Punches and devices also
  reference site now. Fix: extend site_in_use to count punches and devices.
- work_pattern patch audit `new_value` records pre-patch days (the response
  is correct after db.expire_all(); the audit snapshot is not). Fix:
  db.expire(p, ['days']) after db.flush(), before the AuditLog add.
- btree_gist EXCLUDE constraints for shift_rate_rule and
  employee_work_pattern overlap: enforced in application code only.
- Device model was corrected in 2A to add row_version and the unique
  constraint. Older callers may need to set row_version explicitly.
- Deprecations: Employee.work_pattern_id, default_shift_id. Remove after 2C.

## What only the user can supply

- SA statutory tables for the payroll engine, from official sources, no
  placeholders, effective-dated with source reference. The engine refuses
  to run without valid unexpired tables.
- Official SA public-holiday dates per year for 2B. Until supplied, 2B
  must raise setup_error holiday_calendar_missing.
- Standard hours for the hourly-equivalent calculation (the "D5" decision
  deferred from 2A).
- Hand-worked payslips for the payroll engine's golden tests (Chapter 4).
- Confirmation of the A10 auditor scope decision (I followed section 6).

## Exact next step (at 2A close, historical)

Open 2B with a SPEC, no code. The SPEC must cover:

1. Two-tier attendance_day / attendance_segment from the brief, or a
   simpler derived model for the first pass. Source_refs traceability from
   payslip line to attendance segment depends on the two-tier form.
2. Whether public-holiday-not-worked is computed in 2B or deferred to 2C.
3. Whether overtime approval is per-shift only (current model) or also
   per-department (brief allows both).
4. The standard-hours value (D5), which you supply.
5. Recompute trigger: synchronous on adjustment, or a job. Today no job is
   wired to attendance; the dev job runner exists behind an interface.

## Chapter 2B closed (attendance calculation)

2B delivered and committed at 30dbfe0. 644 tests passing (569 from 2A + 75 from 2B).

### What 2B added

Migrations: 0013 (attendance_day, attendance_segment, country_calendar),
0014 (shift.grace_mode, shift.pay_early_arrival).

`attendance_engine.py` (~750 lines):
- Pure: `round_clock_time`, `apply_grace_arrival`,
  `apply_grace_departure`, `build_sessions`, `detect_shift`,
  `determine_day_type`, `split_at_midnight`, `apply_overtime_tiers`,
  `build_day`.
- DB: `ensure_days`, `recompute_day`, `_load_holiday_set`,
  `_holiday_set_for`, `_employee_expected`, `_persist_day`,
  `_advisory_lock_key` (B8: `pg_advisory_xact_lock(int4, int4)` per
  employee+date).

`attendance_schemas.py`: `SegmentOut`, `DayOut`, `DayDetailOut`,
`DayListOut`, `RecomputeIn`, `RecomputeOut`.

`attendance.py` router (3 endpoints, `ATTENDANCE_VIEW` on reads,
`ATTENDANCE_ADJUST` on recompute):
- `GET /attendance/day` — cursor list, filters, `apply_scope`.
- `GET /attendance/day/{employee_id}/{work_date}` — with segments,
  `assert_in_scope`, IDOR-safe 404.
- `POST /attendance/recompute` — `ensure_days` then `recompute_day`
  per date, scope-limited via `apply_scope`, locked days skipped.

Punch trigger: `_process_punch` (in `punches.py`) calls `recompute_day`
for the punch's local date AND the previous local date, so an out-punch
at 06:00 next morning closes a session that started the day before.
Failure is swallowed with `db.rollback()` so the punch is never lost;
diagnostic `[TRIGGER]` prints to stderr remain for now (low volume;
removed in a future cleanup).

### Amendments B1–B14 as implemented

- **B1** (D5 standard hours): no `standard_hours` in code. Segments
  store `rate_method` + `rate_value` as config; converting multiplier
  to money is Phase 4 with contracted weekly hours per employee (the
  `Employee` column does not exist yet; Phase 4 adds it per B1, formula
  confirmed by accountant).
- **B2** (dates): `work_date` = local date the shift STARTS;
  `segment.local_date` = real calendar date of the segment. Documented
  in model and engine. Night shift is one day with segments on two
  dates.
- **B3** (minutes): `worked = normal + overtime`. `raw_minutes` added
  (elapsed minus unpaid break, before rounding/grace). Below-min
  overtime drops to 0 and flags `overtime_below_minimum`. Invariant
  `sum(segment.minutes) == worked_minutes` tested in 2B-3a.
- **B4** (grace): `shift.grace_mode` (`threshold` or `allowance`).
  `threshold`: late beyond grace counts full lateness from scheduled
  start. `allowance`: only excess beyond grace counts. Symmetric for
  early departure.
- **B5** (early arrival): `shift.pay_early_arrival` bool. False: time
  before scheduled start is unpaid, flags `early_arrival_ignored`.
  True: early minutes are overtime and follow approval setting.
- **B6** (shift detection): preferred shift (`expected_shift_id` over
  `default_shift_id`) wins even outside tolerance and flags
  `outside_tolerance`. `no_shift_match` only when no known shift and
  none within tolerance.
- **B7** (sweep): `ensure_days(scope, from_date, to_date)` creates
  rows for days with no punches (`absent` / `missing_punch` /
  `public_holiday_unworked` / `clocks=false`-synthetic). Today is
  tenant-local. Never creates future days. No leave overlay yet
  (Chapter 3 will trigger recompute on approval per B10).
- **B8** (concurrency): `pg_advisory_xact_lock` per
  `(employee_id, work_date)`. Locks are transaction-scoped and
  released automatically on commit/rollback. Cross-thread test
  deferred to Phase 5; the lock is exercised on every recompute, so
  a bug manifests as `DeadlockDetected` at runtime, not silent failure.
- **B9** (holiday calendar): `country_calendar` table + validator.
  Fails closed with `holiday_calendar_missing` when the year has no
  rows. Bug fixed mid-2B: year check was scoped to the requested date
  range instead of the whole year.
- **B10** (leave): no leave input in `ensure_days`/`recompute_day`
  yet. Chapter 3 triggers recompute on approval.
- **B11** (source_version): increments only when computed output
  changes (status, minutes, segments, flags). `computed_at` updates
  on every successful recompute. Tested idempotency: recompute with
  no change keeps `source_version`.
- **B12** (guards): `sites.py site_in_use` counts employees + punches
  + devices. `shifts.py shift_in_use` counts rate_rules +
  work_pattern_days + employees + attendance_days. Recompute endpoint
  applies `apply_scope` to target employees.
- **B13** (rounding): `round_clock_time` applies to clock-in and
  clock-out before session build. `nearest` = half up. No
  segment-level rounding.
- **B14** (tests): 51 pure + 7 DB + 10 endpoint + 4 trigger = 72 new
  tests. Covers B4–B13, timezone splits (SA + NY), minutes
  invariant, locked-day skip, holiday-calendar fail-closed.

### Open items carried from 2B

- 5 MB batch body cap (A6) still not enforced at HTTP layer.
  Middleware recommended before phone clock-in ships.
- Photo happy path not tested (would write to StorageDep). Needs a
  test override in `conftest.py`, not production code.
- No scheduler yet. `ensure_days` callable via
  `POST /attendance/recompute` but production needs a daily job to
  sweep absent days past their grace. Chapter 5 report scheduler can
  host it, or a dedicated cron in the job-runner interface.
- Cross-thread concurrency test for the advisory lock deferred to
  Phase 5.
- `Employee` contracted weekly hours column does not exist. Phase 4
  adds it per B1.
- Diagnostic `[TRIGGER]` prints in `punches.py` — intentional now,
  removed in a later cleanup.

### Next

2C attendance work surface: exceptions queue, single + bulk
adjustments, attendance sheet (monthly grid + daily list API).
SPEC-only first, one approval, then scripts.


## Chapter 2C closed (attendance work surface)

2C delivered. 692 tests passing.

### What 2C added

Exceptions queue (``/attendance/exceptions``): list, single GET, resolve,
bulk_resolve. Engine raises exceptions for missing punches, out-of-
tolerance shifts, below-minimum overtime, missing holiday calendar.
Resolution closes the exception and triggers recompute.

Adjustments (``/attendance/adjustments``): single and bulk with dry-run
token gate, all-or-nothing, revert. Self-adjust refused (403), locked
days refused (409). Audit writes a day snapshot on each adjustment.
Manager and HR both allowed; mandatory reason_code. ADJUSTED DAYS ARE
NOT MARKED ON THE SHEET (audit log only) - C2 rule tested across every
role.

Sheet (``/attendance/sheet``, ``/attendance/daily``,
``/attendance/mark_reviewed``): monthly grid per employee per day; daily
list one row per employee per date with open_exception_count; bulk
mark_reviewed that refuses any day with open_exception_count > 0 and
returns refused_days with reason.

### Decisions inside 2C (recorded)

- C1 audit writes old/new snapshot for each adjustment.
- C2 adjusted days are indistinguishable on the sheet (only audit shows).
- C3 mark_reviewed refuses any day with open_exception_count > 0.
- Closed (locked) attendance days cannot be adjusted; only payroll_admin
  reopens (Phase 4 wiring).
- Sheet column set: employee+date+status+minutes+flags+locked+reviewed.

### 2C tests added

- ``test_exceptions.py``: engine raising, resolve, bulk_resolve.
- ``test_adjustments.py``: single + bulk, dry-run gate, all-or-nothing,
  revert, self-adjust 403, locked 409, audit snapshot. Was untracked
  in git until 2C-6; now in repo.
- ``test_sheet.py``: basic sheet; C2 across all roles; daily
  one-row-per-employee; mark_reviewed happy path; refuses open exceptions.
- ``test_permissions.py``: 15 endpoint-level permission-wiring tests
  for sheet/daily (ATTENDANCE_VIEW) and mark_reviewed
  (ATTENDANCE_ADJUST), each across all five roles. Catches a future
  route that forgets Depends(require_permission(...)).

### Open items carried from 2C

- Leave overlay not wired yet (B10). Chapter 3 approval -> recompute.
- No scheduler. ``ensure_days`` still manual; daily sweep job needed
  before production.
- 5 MB batch body cap still not enforced at HTTP layer.
- Photo happy path still not tested.

### Next

Chapter 3 (requests). SPEC-only first, one approval, then scripts.

# END OF FILE
