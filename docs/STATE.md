# Backend state

## Payroll settings approval flow (gap)
Money-affecting payroll settings (`sdl_applies`, `net_pay_floor`, and the
Chapter 4H closing fields added by `ten_0021`) are changed via direct
`PATCH /payroll/settings` by a user holding `PAYROLL_FINALISE`. There is no
separate approval workflow. Before/after values are audited.

## System earning types auto-seed
**Closed in B4-02f.** `provision_tenant` seeds 13 system earning types at
provisioning time.

## Chapter 4H B-4 progress — core complete
- **B4-01** (committed): migration `ten_0021`, `PayrollSettings` extension.
- **B4-02a** (committed): demo seed pay setup.
- **B4-02b** (committed): 13 system earning types.
- **B4-02c.1** (committed): attendance-to-earnings integration in
  `payroll_runner`.
- **B4-02c.2** (committed): demo seed `ShiftRateRule` rows + 16 tests.
- **B4-02d.1** (committed): finalise open-exceptions ack.
- **B4-02e** (committed): demo PDF watermark.
- **B4-02f** (committed): provision auto-seeds 13 system types.
- **B4-02d.2** (committed): end-to-end demo preview + non-demo 409.

## Chapter 4H B-3 — committed in this bundle
- **B-3.1** `GET /payroll/pay-periods/{period_id}/preview/{employee_id}`
  (single-employee preview detail; `PAYROLL_PREVIEW`).
- **B-3.2** `GET /payroll/payslips/me`, `/me/{id}`, `/me/{id}/pdf`
  (`SELF_VIEW`, self-service, own payslips only, finalised only).
  - Registered BEFORE `/{payslip_id}` so `me` is not parsed as a UUID
    (round-2 §12, tested in `test_me_not_parsed_as_id_by_route`).
  - Auditor role refused with 403 (round-2 §13, tested per-role).
  - `no_employee_record` (404) for users without `employee_id`.
- **B-3.3** 4G-b paylip endpoints unchanged (already implemented,
  verified by content).
- **B-3.4** PDF responses add `Cache-Control: no-store` and generic
  `filename="payslip.pdf"`; the generic `/{payslip_id}/pdf` audits when
  the caller is not the payslip's employee (round-2 §14).
- `payroll_runner._write_payslip` now persists one `PayslipLine` per
  earning/deduction so the new detail endpoint can surface line breakdown
  without recomputation.

## Chapter 4H remaining
- **B4-03 (4G-c)**: golden payslip-case framework — deferred.
- **B-6**: multi-value type filter on `GET /attendance/exceptions` —
  pending.
- **14 seed tests**: session-scoped seed-once fixture — pending.
