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