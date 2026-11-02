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
**Closed in B4-02f.** `provision_tenant::_seed_tenant_defaults` calls
`ensure_system_earning_types` in the same provisioning flow as the company
row insert. A fresh real tenant has 13 `EarningType` rows before the first
request lands.

## Chapter 4H B-4 progress
- **B4-01** (committed): migration `ten_0021`, `PayrollSettings`
  extension, PATCH validation + audit.
- **B4-02a** (committed): demo seed pay setup.
- **B4-02b** (committed — 13 system earning types + demo
  `attendance_earning_map`).
- **B4-02c.1** (committed): attendance-to-earnings integration in
  `payroll_runner`.
- **B4-02c.2** (committed): demo seed `ShiftRateRule` rows + 16
  attendance-earnings tests.
- **B4-02d.1** (committed): finalise open-exceptions ack + preview
  surfaces per-employee `attendance_warnings`.
- **B4-02e** (committed): demo PDF watermark.
- **B4-02f** (committed): provision auto-seeds 13 system types.
- **B4-02d.2** (this bundle): end-to-end demo-tenant preview test
  (`run_preview` → `Payslip` → `render_payslip_pdf` with DEMO watermark)
  + non-demo fail-closed test (unset `unpaid_day_behaviour` → 409).

**B-4 core work is complete.** Remaining sub-bundles within Chapter 4H are
B-3 (single-employee preview + own payslips + 4G-b confirmation), 4G-c
(golden payslip case framework), B-6 (multi-value type filter on
exceptions), and the 14 seed tests.

## Payroll golden cases (Chapter 4H, 4G-c)
- Framework: not yet delivered (Bundle B4-03).
- Pending from accountant: (none yet).
- Reviewed: 0.
- Unreviewed: 0.
