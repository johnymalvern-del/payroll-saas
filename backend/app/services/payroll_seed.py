"""System payroll seed (Chapter 4, Bundle 004a-iv-c + Chapter 4H B-4b).

Idempotent seed of the system earning types required by the attendance-to-
earnings integration (Chapter 4H B-4). All types are `frequency="regular"`
per F5 - only genuine one-offs (bonus, commission, advances) use
once_off/irregular and are refused under the regular-earnings method.

Chapter 4H B-4b additions:
  - `hourly_normal`, `hourly_saturday`, `hourly_sunday`,
    `hourly_public_holiday`
  - `overtime_t1`, `overtime_t2`, `overtime_t3`
  - `shift_allowance`
  - `leave_paid`
These are the earning-type codes that `attendance_earning_map` may reference.

Chapter 4H B-4f: `provision_tenant::_seed_tenant_defaults` calls
`ensure_system_earning_types` at provisioning time, so a freshly created
real tenant has all 13 rows before the first request lands. A call to
`ensure_system_earning_types` on such a tenant returns `created=[]`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant.models.pay import EarningType


SYSTEM_TYPES: tuple[dict, ...] = (
    {
        "code": "normal_pay",
        "name": "Normal Pay",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "overtime",
        "name": "Overtime",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "holiday_pay",
        "name": "Holiday Pay",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "leave_pay",
        "name": "Leave Pay",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "hourly_normal",
        "name": "Normal Hours (Weekday)",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "hourly_saturday",
        "name": "Saturday Hours",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "hourly_sunday",
        "name": "Sunday Hours",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "hourly_public_holiday",
        "name": "Public Holiday Hours",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "overtime_t1",
        "name": "Overtime Tier 1",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "overtime_t2",
        "name": "Overtime Tier 2",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "overtime_t3",
        "name": "Overtime Tier 3",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "shift_allowance",
        "name": "Shift Allowance",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
    {
        "code": "leave_paid",
        "name": "Paid Leave",
        "calc_method": "per_hour",
        "frequency": "regular",
        "is_taxable": True,
        "counts_for_uif": True,
        "counts_for_sdl": True,
        "proration_rule": "none",
    },
)


def ensure_system_earning_types(db: Session) -> dict:
    """Idempotent. Existing rows (by code) are left untouched even if fields
    differ - we do not silently rewrite system rows after they have been used.
    """
    created: list[str] = []
    existing: list[str] = []
    for spec in SYSTEM_TYPES:
        row = db.scalar(select(EarningType).where(EarningType.code == spec["code"]))
        if row is not None:
            existing.append(spec["code"])
            continue
        db.add(EarningType(
            id=uuid.uuid4(),
            name=spec["name"],
            code=spec["code"],
            calc_method=spec["calc_method"],
            frequency=spec["frequency"],
            is_taxable=spec["is_taxable"],
            counts_for_uif=spec["counts_for_uif"],
            counts_for_sdl=spec["counts_for_sdl"],
            proration_rule=spec["proration_rule"],
            is_system=True,
            is_active=True,
        ))
        created.append(spec["code"])
    db.flush()
    return {"created": created, "existing": existing, "total": len(SYSTEM_TYPES)}
