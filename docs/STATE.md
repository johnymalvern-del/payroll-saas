# Backend state

## Payroll settings approval flow (gap)
Money-affecting payroll settings (`sdl_applies`, `net_pay_floor`, and the
Chapter 4H closing fields added by `ten_0021`) are changed via direct
`PATCH /payroll/settings` by a user holding `PAYROLL_FINALISE`. No
two-person control. Before/after values are audited.

## System earning types auto-seed
**Closed in B4-02f.** `provision_tenant` seeds 13 system earning types
at provisioning time.

## Chapter 4H B-4 — core complete
All B-4 sub-bundles committed (B4-01, B4-02a/b/c.1/c.2/d.1/d.2/e/f).

## Chapter 4H B-3 — committed
`GET /payroll/pay-periods/{period_id}/preview/{employee_id}`,
`GET /payroll/payslips/me{,/{id},/{id}/pdf}`. Registered in that order so
`me` is not parsed as a UUID. Auditor 403 on /me. PDF `Cache-Control:
no-store` + generic filename + audit on non-owner download.

## Chapter 4H B-6 — committed
`GET /attendance/exceptions` accepts repeated + comma `type` params;
unknown codes ignored; empty = no filter.

## Payroll golden cases (Chapter 4H, 4G-c)
Framework committed under `backend/tests/golden_payslips/`:

- `_schema.py` (Pydantic; `reviewed_by`/`reviewed_on` required when
  `accountant_reviewed=true`).
- `README.md` — accountant-facing instructions + statutory fixture
  documentation.
- 2 placeholder case files (unreviewed).
- `backend/tests/test_golden_payslips.py` — 6 framework tests.

**Pending from accountant:**

- 2 placeholder cases need filling in and signing off
  (`accountant_reviewed: true` + `reviewed_by` + `reviewed_on`).
- Additional cases as the accountant prepares them.

**Reviewed:** 0
**Unreviewed:** 2
**Tests state:** `test_golden_unreviewed_cases_skipped_loudly` skips
with file names listed; `test_golden_reviewed_cases_pass` skips because
0 reviewed.

## Chapter 4H remaining
- **14 seed tests** — session-scoped seed-once fixture (needs
  `conftest.py`).

## Chapter 3 — L1 (3B leave types & balances) committed

- **L1a** migration ten_0022: leave_type.approval_chain, leave_type.requires_payroll_admin_final; payroll_settings leave_escalation_days, leave_cycle_fixed_anchor, advance_max_pct, advance_hard_cap, sick_leave_codes, net_estimate_method. audit_redact extended with leave_reason, advance_reason, grievance_subject/body/note, resolution_note, sick_note_*. 
- **L1b** leave types CRUD: GET/POST/PATCH/deactivate/reactivate at `/api/v1/leave/types`. Permission: GET = LEAVE_APPROVE OR SELF_VIEW; writes = USER_MANAGE. approval_chain defaults ["manager","hr"]. Business rules: accrual_amount required for annual/fixed, negative-requires-accrual, no-carryover-on-fixed. Code immutable on PATCH. 
- **L1c** leave balances: GET list + single at `/api/v1/leave/balances`; POST /adjust. Adjust writes LeaveBalanceLedger (reason="adjustment"), refuses 422 insufficient_balance when resulting available<0 and allow_negative=false. Adjusting closed cycle requires PAYROLL_FINALISE. Auto-creates missing live-cycle balance. 
- **L1c** `payroll_engine/leave.py`: compute_cycle_bounds (calendar/anniversary/fixed), available_balance = accrued + carried_in + adjusted - taken - pending (entitled informational only, per amendment 4). 
- **L1d** accrual: POST `/api/v1/leave/accruals/run` (USER_MANAGE). `accrue_all_employees(db, as_of)` computes period keys per cycle, idempotent via reason="accrual:<period_key>". Carry-over honoured at cycle creation, respects leave_type.max_carryover. Migration ten_0023 adds payroll_settings.last_accrual_run_at. GET /leave/balances now returns `accrued_as_of` + `accrual_stale` (True when last run is None or >1 day old). GETs never write. 
- **L1e** tests: `test_leave_types.py`, `test_leave_balances.py`, `test_leave_accruals.py` — covers create/dup/validators/PATCH/immutability/deactivate-refused-in-use/list-filters/approval-chain defaults, available_balance numeric formula (entitled excluded), self-vs-approver scope, adjust positive/negative/closed-cycle/ledger/auto-create, GET-never-writes, accrual monthly/annual/fixed/none, idempotency, carry-over max vs full, endpoint counts, stale/fresh detection.

Pending chapter 3: L2 (3C leave requests + approval chain + attendance adjustments on approval), L3 (3D attachments/sick notes), L4 (3E advances + 3F grievances), L5 (3G /me aggregator + daily-jobs CLI + demo seed extension). Refer to Chapter 3 amendments 1–12 (approval_chain configurable, approved-leave creates adjustments, accrual never lazy-on-read, day-only for now, sick-note POPIA rules, audit redaction, capture-on-behalf, grievance notes, advance repayment_plan typed, 5-bundle split).

## M5 — Monthly salary sheet (committed, `c600884`)

`GET /payroll/pay-periods/{period_id}/salary-sheet` — read-only
company-wide salary sheet for a pay period, backed by persisted
`Payslip` / `PayslipLine` rows. No call to
`payroll_runner.run_preview` / `finalise` / `run_pipeline`; the sheet
cannot trigger or invalidate a payroll run.

- **Permission:** `PAYROLL_PREVIEW` (hr, payroll_admin). Refused for
  employee, manager, auditor — matches the permission matrix.
- **Scope:** `apply_scope(..., model=Payslip)` on `Payslip.employee_id`
  composes inside the same query as the `q` search predicate — a
  scoped HR user cannot search out of their scope.
- **States:**
  - `figures_state = "finalised"` → `PayPeriod.status == "locked"`,
    reads `Payslip.status == "current"`.
  - `figures_state = "preview"` → `PayPeriod.status == "open"`,
    reads `Payslip.status == "preview"`.
  - `figures_state = "no_preview"` → open period with zero preview
    rows.
- **Figures:** every column except `basic_earnings` /
  `additional_earnings` is a byte-for-byte copy of a `Payslip` column.
  Basic = sum of `PayslipLine.amount` where `line_type="earning"` and
  `source_ref.earning_type_code="BASE_MONTHLY"`; Additional = sum of
  the remaining earning lines. So `basic_earnings + additional_earnings
  == gross`, and all figures match the payslip PDF.
- **Pagination:** composite cursor over `(employee_code, payslip_id)`
  matching `ORDER BY employee_code ASC, payslip_id ASC`. A UUID-only
  cursor would re-serve rows because `Payslip.id` is a random UUID;
  fixed by carrying `employee_code` in the cursor payload.
- **Query param normaliser:** `q` / `limit` / `cursor` are normalised
  to their intended types at the top of the handler so tests that call
  the function directly (bypassing FastAPI `Query` resolution) match
  HTTP behaviour. No effect on HTTP semantics; `Query(ge=1, le=500)`
  on `limit` still validates over the wire.
- **Schemas:** `backend/app/api/v1/payroll_salary_sheet_schemas.py`
  (`SalarySheetRow`, `SalarySheetOut`).
- **Tests:** `backend/tests/test_payroll_salary_sheet.py` (9) —
  permission matrix, preview / finalised / no-preview, basic vs
  additional split from `PayslipLine`, reconciliation with `Payslip`,
  employee search, composite cursor pagination, period-not-found.
- **Full backend suite at commit:** **1336 passed / 4 skipped /
  0 failed**.

### Known limitations (backend)
- **Preview must be run first.** An open period with no preview
  returns `figures_state = "no_preview"` and zero items; the frontend
  prompts the user to open pay-period detail and Preview. Read-only by
  design.
- **Superseded payslips not surfaced** — after reopen, prior-current
  payslips have `status = "superseded"`; the sheet filters to
  `"preview"` / `"current"` only, matching the `list_payslips` default.

### Documentation gap

The preceding entries in this file stop at Chapter 3 L1. M4 backend
stages (B-L4a awaiting-approver queue filter + `LeaveRequestOut`
display fields; B-L4b row lock on leave decisions; B-L5a advisory
locks + schema hardening) are on disk and committed, but are not
recorded here in the pasted copy of the file. Flagged, not filled —
the git history at `c600884` is the authoritative record. To be
backfilled in a dedicated docs pass if desired.

## Payroll / Scope (M6 Stage A)

**HR default scope is fail-open — documented risk, not fixed in M6.**

- `app/core/scope.py:109-113` — HR users with **zero** `UserScope` rows
  receive company-wide employee visibility. This is intentional existing
  behaviour relied upon by `tests/test_seed_demo.py:194` (the demo HR user
  is seeded without scope rows).
- Tenant provisioning **must** add `UserScope` rows for any HR user who
  should be branch-restricted. Missing rows are not detected — the HR
  user simply sees every employee in every branch.
- Manager scope (`app/core/scope.py:115-121`) is fail-**closed** — a
  manager with no direct reports and no scope rows sees nobody. The
  asymmetry is deliberate but means HR onboarding requires deliberate
  scope-row setup.
- **Known business/security risk requiring a separately planned future
  milestone.** A fail-closed default for HR would need: a
  `scope_type="company"` sentinel or a `Company.hr_default_scope`
  setting, a demo-seed update, a migration to backfill existing tenants,
  and an admin UI for `UserScope` management. None of those exist today;
  changing the default without them would break access for every tenant
  where HR currently relies on the fail-open behaviour. Documented here,
  not fixed in M6 Stage A.

### Preview response scope (M6 Stage A)

`POST /payroll/pay-periods/{id}/preview` — the **calculation** remains
company-wide (`payroll_runner.run_preview` and `_in_scope_employees`
unchanged), but the **HTTP response** is scope-filtered via
`apply_scope(..., model=Payslip)`. A branch-scoped HR triggering a
preview runs the full company calculation but only receives their
in-scope employees in `items[]`. Payroll administrators receive all
employees. M5 salary-sheet behaviour unchanged.

### Change-request scope (M6 Stage A)

`GET /payroll/change-requests` (list) and `GET /payroll/change-requests/{id}`
(detail) now enforce employee scope. Approve / reject / cancel enforce
scope via the private `_load_scoped_request` helper — 404 for out-of-scope
requests, indistinguishable from nonexistent records. Submission (`POST`)
already enforced scope and is unchanged. The permission matrix is
unchanged; approve/reject remain payroll-admin-only, with the added
`assert_in_scope` as defence-in-depth for any future permission grant.

### Empty-preview state (M6 Stage A)

`PreviewOut.raw_employee_count` (from `run.rules_snapshot["employee_count"]`)
and `SalarySheetOut.figures_state="preview_out_of_scope"` distinguish
"no preview has been generated" from "a preview exists but no employees
in the caller's scope." Both backend and frontend surface this
distinction.