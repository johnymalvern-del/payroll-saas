"""System payroll seed (Chapter 4, Bundle 004a-iv-c).

Idempotent seed of the four system earning types (normal_pay, overtime,
holiday_pay, leave_pay) required by the pipeline for standard SA payroll.
All four are classified `frequency="regular"` per F5 - only genuine one-offs
(bonus, commission, advances) use once_off/irregular and are refused under
the regular-earnings method.

Called from:
  - POST /payroll/earning-types/ensure-system  (this bundle)
  - import_employees.py on first import (future refinement, noted in STATE.md)
  - provision_tenant post-migration hook (future refinement, noted in STATE.md)

Never from tests' disposable-tenant fixture directly - they call the endpoint
or the service function explicitly so the seed state is deterministic.
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
)


def ensure_system_earning_types(db: Session) -> dict:
    """Idempotent. Existing rows (by code) are left untouched even if fields differ -
    we do not silently rewrite system rows after they have been used."""
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

# END OF FILE
