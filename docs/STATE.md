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