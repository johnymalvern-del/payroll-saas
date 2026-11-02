# Backend state

## Payroll settings approval flow (gap)
Money-affecting payroll settings (`sdl_applies`, `net_pay_floor`, and the
Chapter 4H closing fields added by `ten_0021`) are changed via direct
`PATCH /payroll/settings` by a user holding `PAYROLL_FINALISE` (today:
`payroll_admin`). There is no separate approval workflow: the acting user
both proposes and commits.
- Before/after values are written to the audit log
  (`payroll_settings.update` action) on every PATCH.
- **Gap**: a two-person control (proposer + approver) for money-affecting
  settings does not exist. To close: introduce a
  `payroll_settings_change_request` table plus approve/reject endpoints,
  mirroring `payroll_change_request`.

## System earning types auto-seed (gap)
`provision_tenant` does not call `ensure_system_earning_types` in
`_seed_tenant_defaults`. A freshly provisioned real tenant has zero
`EarningType` rows until the user calls
`POST /payroll/earning-types/ensure-system`, or until the first
`run_preview`/`finalise` (which calls it internally).
- **Impact**: limited — runner self-heals on first preview, but
  `GET /payroll/earning-types` returns empty until then.
- **To close**: import `ensure_system_earning_types` in
  `provisioning.py::_seed_tenant_defaults`; needs `provisioning.py` source.
  Recorded for a future bundle.

## Chapter 4H B-4 progress
- **B4-01** (committed): migration `ten_0021`, `PayrollSettings`
  model/schema extension, PATCH validation + audit.
- **B4-02a** (committed): demo seed pay setup.
- **B4-02b** (committed): 13 system earning types + demo
  `attendance_earning_map`.
- **B4-02c.1** (this bundle): attendance-to-earnings integration in
  `payroll_runner`. `_build_attendance_earnings` reads
  attendance_day+attendance_segment for the period, groups by
  `attendance_earning_map`, resolves rate-in-force via
  `EmployeePayHistory`, negates unpaid-day / unpaid-PH amounts (round-2
  §3), skips unapproved overtime with a warning (round-2 §6), requires
  `monthly_hourly_derivation_formula_code` for monthly staff OT/premium
  (round-2 §4), rejects `leave_authoritative_source` other than
  `'adjustment'` (round-2 §9). Snapshot stored on
  `draft.calculation_context["attendance_inputs"]` (round-2 §10).
  `FORMULA_REGISTRY` unchanged at 6 (derivation formulas live in
  `DERIVATION_FORMULAS`); `_validate_formula_code` in
  `payroll_settings.py` accepts either set.
- **B4-02c.2** (pending): demo seed `ShiftRateRule` rows + SEED.md
  update + `tests/test_payroll_attendance_earnings.py`.
- **B4-02d** (pending): finalise open-exceptions acknowledgement +
  `PreviewOut.warnings` surfaced from
  `Payslip.calculation_context["attendance_warnings"]` + end-to-end
  gross→PAYE→UIF→net test with fake control tables.
- **B4-02e** (pending): demo PDF watermark via
  `payroll_pdf.render_payslip_pdf` when `PayrollSettings.demo_values`.
- **B4-02f** (pending): `provisioning.py` auto-seed hook.

## Payroll golden cases (Chapter 4H, 4G-c)
- Framework: not yet delivered (Bundle B4-03).
- Pending from accountant: (none yet).
- Reviewed: 0.
- Unreviewed: 0.
