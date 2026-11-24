# Retention Operations Runbook

Operational procedures for the GPS coordinate retention sweep required by
section 5 of `BIOMETRIC_PRIVACY_AND_RETENTION_POLICY.md`.

This document is for whoever operates the system. It is deliberately concrete:
a retention obligation that depends on someone remembering an undocumented
command is not a control.

---

## 1. What the sweep does

Deletes rows from `punch_location` that are older than the retention window
(30 days by default). The `punch` row itself is never touched — it keeps
`geofence_result`, `geofence_reason` and `distance_band` permanently.

Coordinates exist in exactly one place after `ten_0031`: `punch_location`.
Deleting a row there is a genuine removal, not an overwrite.

**Exceptions hold evidence.** If an employee has an open `exception_item` for
a given work date, that day's coordinates are skipped. The hold is released
automatically when the exception is resolved or dismissed; there is no flag to
clear.

**Locked attendance days do not hold.** A finalised payroll period keeps the
verdict, not the position. This is deliberate: locked days stay locked, so
holding on them would mean retaining coordinates forever.

---

## 2. Command
