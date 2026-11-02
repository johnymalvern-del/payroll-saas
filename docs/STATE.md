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
  mirroring `payroll_change_request`. Recorded here so the gap is not
  silently forgotten.

## Payroll golden cases (Chapter 4H, 4G-c)
- Framework: not yet delivered (Bundle B4-02).
- Pending from accountant: (none yet).
- Reviewed: 0.
- Unreviewed: 0.

## Chapter 4H B-4 progress
- **Bundle B4-01 (this bundle)** — migration `ten_0021`, `PayrollSettings`
  model/schema extension, PATCH validation + audit. No attendance
  integration yet.
- **Bundle B4-02 (deferred)** — attendance-to-earnings integration in
  `payroll_runner._build_earnings` / `build_pipeline_config`. Requires the
  `payroll_engine` module outline; not yet written.
