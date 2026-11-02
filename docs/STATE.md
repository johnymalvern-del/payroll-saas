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

## System earning types auto-seed
**Closed in B4-02f.** `provision_tenant::_seed_tenant_defaults` now calls
`ensure_system_earning_types` in the same provisioning transaction as the
company row insert. A freshly provisioned real tenant has 13
`EarningType` rows before the first request lands, so `GET
/payroll/earning-types` returns a populated list without requiring a
manual `POST /payroll/earning-types/ensure-system` call.

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
- **B4-02e** (committed): demo PDF watermark via `payroll_pdf`.
- **B4-02f** (this bundle): `provision_tenant` auto-seeds the 13 system
  earning types. Closes the "System earning types auto-seed" gap above.
- **B4-02d.2** (pending): demo-tenant preview e2e + non-demo unset 409
  (needs control-table fixtures in test).

## Payroll golden cases (Chapter 4H, 4G-c)
- Framework: not yet delivered (Bundle B4-03).
- Pending from accountant: (none yet).
- Reviewed: 0.
- Unreviewed: 0.
