"""Import-field helpers (Chapter 4, Bundle 004a-iv-c).

The three payroll-specific employee fields (contracted_weekly_hours,
medical_scheme_members, uif_exempt) must be set through the same approval
mechanism as pay-rate changes (F3). This module provides:

  - IMPORT_FIELDS: the three field names a CSV/JSON row may supply.
  - validate_import_row_fields(row_dict) -> list[str]: returns a list of
    validation errors (empty if OK). Caller is expected to fail the whole
    import batch on any error.
  - apply_import_row_fields(employee, row_dict) -> bool: writes the three
    fields to `employee` if present; returns True if any was written.

Wiring into import_employees.py is a documented follow-up (STATE.md at close).
The helper is deliberately side-effect-free on the Employee until the caller
commits, so no partial writes.

The three fields, once imported, still require payroll_admin approval to take
effect on payroll - imported values on Employee are only a stored snapshot.
Enforcing F3 on the payroll run is what the pipeline actually consumes.
"""
from __future__ import annotations

from typing import Any

from app.db.tenant.models.people import Employee


IMPORT_FIELDS: tuple[str, ...] = (
    "contracted_weekly_hours",
    "medical_scheme_members",
    "uif_exempt",
)


def validate_import_row_fields(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "contracted_weekly_hours" in row and row["contracted_weekly_hours"] is not None:
        try:
            hours = float(row["contracted_weekly_hours"])
            if hours < 0 or hours > 168:
                errors.append(
                    f"contracted_weekly_hours out of range: {hours} (must be 0..168)"
                )
        except (TypeError, ValueError):
            errors.append(
                f"contracted_weekly_hours not numeric: {row['contracted_weekly_hours']!r}"
            )

    if "medical_scheme_members" in row and row["medical_scheme_members"] is not None:
        try:
            members = int(row["medical_scheme_members"])
            if members < 0:
                errors.append(f"medical_scheme_members negative: {members}")
        except (TypeError, ValueError):
            errors.append(
                f"medical_scheme_members not integer: {row['medical_scheme_members']!r}"
            )

    if "uif_exempt" in row and row["uif_exempt"] is not None:
        val = row["uif_exempt"]
        if not isinstance(val, bool) and val not in (0, 1, "0", "1", "true", "false", "TRUE", "FALSE"):
            errors.append(f"uif_exempt not boolean-like: {val!r}")

    return errors


def apply_import_row_fields(employee: Employee, row: dict[str, Any]) -> bool:
    """Mutate `employee` in place for the three payroll fields. Returns True if any
    field was set. Does NOT commit - caller commits within the batch transaction."""
    wrote = False

    hours = row.get("contracted_weekly_hours")
    if hours is not None:
        employee.contracted_weekly_hours = float(hours)
        wrote = True

    members = row.get("medical_scheme_members")
    if members is not None:
        employee.medical_scheme_members = int(members)
        wrote = True

    exempt = row.get("uif_exempt")
    if exempt is not None:
        if isinstance(exempt, bool):
            employee.uif_exempt = exempt
        elif exempt in (1, "1", "true", "TRUE"):
            employee.uif_exempt = True
        elif exempt in (0, "0", "false", "FALSE"):
            employee.uif_exempt = False
        wrote = True

    return wrote

# END OF FILE
