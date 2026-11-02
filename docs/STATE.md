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
- **To close**: import `ensure_system_earning_types` in
  `provisioning.py::_seed_tenant_defaults`. Needs `provisioning.py` source.
  Recorded for a future bundle.

## Chapter 4H B-4 progress
- **B4-01** (committed): migration `ten_0021`, `PayrollSettings`
  model/schema extension, PATCH validation + audit.
- **B4-02a** (committed): demo seed pay setup.
- **B4-02b** (committed): 13 system earning types + demo
  `attendance_earning_map`.
- **B4-02c.1** (committed): attendance-to-earnings integration in
  `payroll_runner`.
- **B4-02c.2** (committed): demo seed `ShiftRateRule` rows + 16
  attendance-earnings tests.
- **B4-02d.1** (committed): finalise open-exceptions ack + preview
  surfaces per-employee `attendance_warnings`.
- **B4-02e** (this bundle): demo PDF watermark. `payroll_runner` writes
  `demo_values` into `calculation_context["attendance_inputs"]["settings"]`
  on every payslip; `payroll_pdf.render_payslip_pdf` prepends/appends a
  `*** DEMO - NOT A REAL PAYSLIP ***` line when the flag is set (or when
  a caller passes `demo_values=True` explicitly).
- **B4-02f** (pending): `provisioning.py` auto-seed hook.
- **B4-02d.2** (pending): demo-tenant preview e2e + non-demo unset 409
  (needs control-table fixtures in test).

## Payroll golden cases (Chapter 4H, 4G-c)
- Framework: not yet delivered (Bundle B4-03).
- Pending from accountant: (none yet).
- Reviewed: 0.
- Unreviewed: 0.
