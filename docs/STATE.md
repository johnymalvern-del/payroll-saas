# Payroll SaaS - Project State

Last updated: close of Chapter 2A (Attendance Foundation).

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
Five multi-line scripts died because their content was pasted into a
terminal instead of saved to disk; ~130 single-line commands followed
because each fix was split into diagnose/patch/verify instead of one
verifiable script.

Rules from 2B onward:

- Every deliverable is one or more **full .ps1 or .py files** saved in VS
  Code. The only typed terminal command is a single `powershell -File
  <path>` or `python -m pytest <args>` invocation.
- Every .ps1 writes its files with `[System.IO.File]::WriteAllText(<absolute
  path>, content)`. No relative paths. No `python -c` with `''` escaping.
- Every .ps1 has a truncation check ("# END OF FILE" as last non-empty
  line) and a `Fail` on any anchor mismatch, so it either applies the whole
  patch or nothing.
- Every .ps1 prints a `PASS` line as its final output. Absence of that line
  means the script did not complete.
- Register new routers in `app/api/v1/__init__.py` in the **same file**
  that creates the router. Two routers (punches, and at one point
  work-patterns) shipped unregistered and only surfaced when an HTTP test
  ran.

## Milestones

### Done (committed)

- 1C.4 company GET/PATCH with row_version
- 1C.4.1 branch scope helpers (apply_branch_scope, assert_branch_in_scope)
- 1C.5 branches CRUD
- 1C.6 sites CRUD
- 1C.6.1 / 1C.6.2 rate-limiter test scoping
- 1C.7 departments CRUD
- 1C.8 employees CRUD with crypto at rest
- 1C.9 users CRUD, user_scope, one active user per employee
- 1C.10 pay-rate-change approval flow, PAY_RATE_VIEW
- 1C.11 employee import (CSV, dry-run + token gate, opening rates)
- 1C.12 audit-log read API (read-audited)
- **2A attendance foundation** (this commit, message begins "Chapter 2A:") -
  see the section "What 2A delivered" below

### Next

- **2B attendance calculation**: session building, shift detection, day
  build (rounding, grace, breaks, overtime tiers, midnight split, day types),
  rate lookup via `find_rule_for_minute`, expected days and absences,
  public-holiday-not-worked, recompute. Blocked on the user supplying the
  standard-hours value (section 6 of the master brief says the engine must
  refuse to run without valid data; D5 was explicitly deferred to 2B).
- **2C attendance work surface**: exceptions queue, single + bulk adjustments,
  attendance sheet (monthly grid + daily list API).
- Then Chapter 3 (requests), Chapter 4 (payroll), Chapter 5 (reports + POPIA),
  Chapter 6 (devices), Chapter 1D (frontend, not started, 0%).

## What 2A delivered

Migration 0012 (amended during 2A, see "Migration 0012 history" below):
8 new tables plus a `device` ALTER. Additive only - `device` already existed
from migration 0001. Punch is append-only: REVOKE UPDATE/DELETE plus a
BEFORE UPDATE OR DELETE trigger. Grants for the 7 new tables applied at the
end of 0012, after 0001's blanket `GRANT ... ON ALL TABLES`.

Models in `app/db/tenant/models/attendance.py`: Shift, ShiftRateRule,
WorkPattern (with `days` relationship), WorkPatternDay, PublicHolidayTenant,
Punch, EmployeeWorkPattern. Device remains in `devices.py`; 0012 adds
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

Punch pure functions (`app/api/v1/punch_service.py`, no DB, no HTTP):
- A2 timing: `effective_time = device_time - offset`; offset is
  `device_now_at_send - server_received` when device_now is present (batch),
  else `device_time - server_received` (live). A live punch resolves to
  server time; an offline batch punch preserves its recorded wall clock.
- A3 idempotency: `canonical_payload_hash` over identity fields only,
  excluding client_punch_id, photo, raw_payload.
- A6: photo magic bytes (JPEG/PNG) + size cap (300 KB default);
  raw_payload template-key rejection (any key named like `template`,
  `fingerprint_template`, `face_template`, `embedding`, case-insensitive)
  and 8 KB cap.
- A4 classifiers: `future_time`, `clock_gap`, `low_confidence`,
  `liveness_failed`.

### Decisions inside 2A (recorded so they are not re-debated)

- D1 `SHIFT_CONFIGURE` (payroll_admin only) for shifts, rate rules, work
  patterns, public holidays, devices. HR does not manage these; HR manages
  employee work-pattern assignments (`EMPLOYEE_CRUD`).
- D2 payroll_admin creates a device and receives the raw key once.
- D3 device auth via `X-Device-Key`; HMAC over punch payloads deferred to
  Phase 6.
- D4 photos optional per device policy.
- D6 shift-detection tiebreak: nearest start time, tie-break lowest id.
- D7 `day_index = (D - anchor_date).days % cycle_length_days`.
- D10 duplicate punches stored with `status="duplicate"` (via 2B; the model
  supports it).
- A1 device keys: `secrets.token_hex(32)`; `hash_device_key` = SHA-256 hex
  (NOT argon2 - argon2 is salted, so a device could not be looked up by
  its key without scanning); lookup by hash, `hmac.compare_digest`. Non-active
  device -> 403 `device_inactive`. Failed attempts rate-limited by IP.
- A2 effective_time computed server-side; the model stores `device_time`,
  `device_now_at_send`, `effective_time`, `offset_ms`.
- A3 `client_punch_id` unique per `(device_id, client_punch_id)`; same pair
  + same `payload_hash` returns the stored row; different hash -> 409
  `punch_uuid_reused`.
- A4 `punch.flags` JSONB list; `status` is immutable.
- A5 unknown employee -> 422 `unknown_employee`; terminated employee ->
  stored `status="rejected"` with `employee_not_active` flag; code-only
  punch -> 403 `code_not_allowed_here` unless `device.allows_code_only`;
  missing photo when required -> 400 `photo_required`. Roaming punches
  flagged `site_mismatch`, not rejected.
- A6 photo byte-level validation, raw_payload template-key scan, 300 KB and
  8 KB caps.
- A7 rate-rule tiers: contiguous from 1; `tier_up_to_minutes` strictly
  increasing; exactly one open-ended top tier. Overlap of effective periods
  for the same key rejected at 409 `overlapping_rate_rule`. Same-period
  siblings are the rule set being extended; the overlap check excludes
  them, or no rule set could ever gain a second tier.
- A8 delete rules: hard-delete only when unreferenced; past-dated rate rules
  and public holidays cannot be deleted, only ended with `effective_to` /
  `is_active=false`. Mirrors the branch/site/department pattern.
- A9 `employee_work_pattern` effective-dated history. `Employee.work_pattern_id`
  and `default_shift_id` are deprecated; 2B reads the new table first and
  falls back to legacy. Remove after 2C.
- A10 `ATTENDANCE_VIEW` permission added, granted to employee, manager, hr,
  payroll_admin per section 6. **The auditor is NOT granted attendance
  view** - section 6 gives the auditor no attendance row. If this was
  intended to change, one line in `permissions.py` and one line in
  `test_auditor_cannot_access_punch_list`.
- A11 `is_working_day_override = true` means "the country calendar says
  this date is a holiday, but for this scope (site or department) it is a
  normal working day". `false` (or a row with no country-holiday match)
  means "the tenant is declaring this date a holiday on top of the country
  calendar". 2B must raise `setup_error holiday_calendar_missing` when the
  year has no holiday data; never treat a missing calendar as "no
  holidays".
- A12 `test_schema_drift.py` iterates `Base.metadata.tables`, skips the six
  control-DB tables by name, and asserts model columns equal
  `information_schema.columns` on the tenant engine.

### Migration 0012 history (so a reader understands the amendments)

Migration 0012 as authored recreated `device`, which already existed from
migration 0001, and the tenant migration failed with `DuplicateTable: device`.
Fixed by replacing the `CREATE TABLE device` with `ALTER TABLE device ADD
COLUMN row_version` and converting `ix_device_api_key_hash` to a UNIQUE
index. 0001's other device choices were kept: `site_id ondelete=CASCADE`
(not RESTRICT), `status DEFAULT 'offline'` (not 'active'),
`api_key_hash VARCHAR(255)`. The endpoint sets `status='active'` explicitly at
create, so the schema default is not load-bearing.

The seven new tables' GRANTs are applied at the end of 0012 because 0001's
`GRANT ... ON ALL TABLES IN SCHEMA public` ran before those tables existed.
`punch` gets only `SELECT, INSERT`; `UPDATE, DELETE` are revoked and the
append-only trigger is the second line of defence.

### Production bug fixed during 2A

`app/core/errors.py`'s `validation_exception_handler` was returning
Pydantic's `exc.errors()` raw. That list contains `ctx.error` as a
`ValueError` instance for any custom `@field_validator`, which
`json.dumps` refuses to serialise. Result: any endpoint with a custom
validator raising `ValueError` returned 500 instead of 422. The handler
now strips `ctx` from each error dict; the human-readable `msg` is kept.
Exposed by shift create with an invalid enum. **Every future phase that
adds a validator would have hit this**; it is fixed once here.

### Chapter 2A stats (per the chapter-mode metrics)

- Scripts delivered: ~20 groups (2A-1a through 2A-8b plus close-out). The
  final count is not precise because several groups spanned multiple
  sub-replies; the primary metric is the 569-test suite, not the reply
  count.
- Scripts that failed first time: roughly 10. Of those, the majority were
  delivery failures - content pasted into a terminal rather than saved to
  disk - not code failures. Actual code defects caught by the process:
  the `.NET ReadAllText(relative_path)` CWD issue; control-DB tables in the
  drift test; backslash `\x` literals becoming ASCII in two places; the
  overlap check rejecting same-period siblings; `Session.get()` returning
  from the identity map after an API delete; `WorkPattern.days` relationship
  missing; three unregistered routers.
- Decisions asked from the user in 2A: 2 (A10 permission shape; auditor
  attendance scope confirmation). Everything else was in the SPEC.
- **What went right**: pure-function service for punches is fully tested
  without a database; the migration is additive and verified against a live
  tenant; the drift test exists and will catch future model-vs-migration
  divergence.

## Open items for 2B / 2C / later phases

- **5 MB batch body cap (A6)** not yet enforced by the endpoint. FastAPI
  does not enforce body size by default. Middleware is the recommended fix;
  not urgent for a single-site kiosk but required before phone clock-in
  goes live.
- **Photo happy path not tested.** Valid photo would write to `StorageDep`
  and leave files. Add a `StorageDep` test override in `conftest.py`, not
  a production code path, then a real test.
- **`sites.py site_in_use` counts employees only.** Punches (`site_id`)
  and devices (`site_id`) now reference sites, so a site with either
  returns 500 on delete. Fix: extend `site_in_use` to count punches and
  devices, mirroring the branch pattern from 1C.6.
- **`work_pattern_patch` audit `new_value` records pre-patch days.** The
  response is correct (fixed with `db.expire_all()` after commit); the
  audit row sees the stale collection. Fix: `db.expire(p, ['days'])` after
  `db.flush()` and before the `AuditLog` add.
- **`btree_gist` EXCLUDE constraints** for `shift_rate_rule` and
  `employee_work_pattern` overlap: enforced in application code only. A
  follow-up migration can install the extension and the constraints.
- **`Device` model was corrected in 2A-2-ii** to add `row_version` and the
  unique constraint; older callers that constructed a Device without
  `row_version` will hit `NOT NULL`. Fixed at all call sites; recorded
  here for new code.
- **Deprecations**: `Employee.work_pattern_id`, `Employee.default_shift_id`.
  Remove after 2C once the fallback path is deleted.

## What only the user can supply

- SA statutory tables (income tax brackets, rebates, thresholds, UIF
  ceiling, SDL rate, medical credits, retirement-fund limits) for the
  payroll engine, from official sources. No placeholder values, ever. The
  engine will refuse to run without valid, unexpired, source-referenced
  tables.
- Official SA public-holiday dates per year, for 2B. Until supplied, 2B
  must raise `setup_error holiday_calendar_missing`.
- Standard hours for the hourly-equivalent calculation (BCEA / contract).
  This is the "D5" decision deferred from the 2A SPEC.
- Hand-worked payslips for the payroll engine's golden tests (Chapter 4),
  supplied as data, not generated from the engine.
- Confirmation of the A10 auditor scope decision above (I have followed
  section 6 as written; if you intended read-only attendance for the
  auditor, say so).

## Exact next step

Open **2B**. Do not write code before 2B's SPEC is approved. The SPEC must
cover:

1. Whether 2B reuses `attendance_day` and `attendance_segment` from the
   master brief or a simpler derived model for the first pass. (Two-tier
   tables are more code but the brief requires source_refs traceability
   from payslip line to attendance; the readiness screen and the drill-down
   depend on it.)
2. Whether public-holiday-not-worked is computed in 2B or deferred to 2C.
3. Whether overtime approval is a per-shift setting (current model) or a
   department setting too (the brief says configurable per shift OR
   department; today only per shift is stored).
4. The standard-hours value (D5), which the user supplies.
5. The recompute trigger mechanism: synchronous on adjustment, or a job.
   Today no job runner is wired to attendance; the dev job runner exists
   behind an interface.

# END OF FILE