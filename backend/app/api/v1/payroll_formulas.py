"""Formula readiness + acknowledgement (Chapter 4, Bundle 004a-i).

F8: the readiness screen warns until each formula is acknowledged by the
payroll admin; the first finalise per tenant refuses if any formula is
unacknowledged. Acks are stored in payroll_settings.formula_acks as JSONB.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_formulas_schemas import (
    AcknowledgeOut,
    FormulaInfo,
    ReadinessOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.services.payroll_audit import write_audit
from app.services.payroll_formulas import FORMULA_REGISTRY

router = APIRouter(prefix="/payroll-formulas", tags=["payroll-formulas"])


@router.get("/readiness", response_model=ReadinessOut)
def get_readiness(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> ReadinessOut:
    settings = db.scalar(select(PayrollSettings).limit(1))
    acks = (settings.formula_acks or {}) if settings is not None else {}
    items: list[FormulaInfo] = []
    for code, description in FORMULA_REGISTRY.items():
        rec = acks.get(code) or {}
        items.append(FormulaInfo(
            code=code,
            description=description,
            verified=code in acks,
            acknowledged_at=rec.get("at"),
            acknowledged_by=rec.get("by"),
        ))
    return ReadinessOut(items=items, all_acknowledged=all(i.verified for i in items))


@router.post("/{code}/acknowledge", response_model=AcknowledgeOut)
def acknowledge_formula(
    code: str,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> AcknowledgeOut:
    if code not in FORMULA_REGISTRY:
        raise AppError("unknown_formula", f"Formula {code!r} not registered", 404)
    settings = db.scalar(select(PayrollSettings).limit(1))
    if settings is None:
        settings = PayrollSettings(
            id=uuid.uuid4(),
            net_pay_floor=Decimal("0.00"),
            formula_acks={},
            row_version=1,
            updated_by_user_id=getattr(user, "id", None),
        )
        db.add(settings)
        db.flush()
    old_acks = dict(settings.formula_acks or {})
    now = datetime.now(timezone.utc)
    new_acks = dict(old_acks)
    new_acks[code] = {
        "at": now.isoformat(),
        "by": str(getattr(user, "id", "")) or None,
    }
    settings.formula_acks = new_acks
    settings.row_version += 1
    settings.updated_by_user_id = getattr(user, "id", None)
    write_audit(
        db, user,
        entity_type="payroll_formula_ack",
        entity_id=settings.id,
        action="acknowledge",
        old_value={"acked": sorted(old_acks.keys())},
        new_value={"acked": sorted(new_acks.keys()), "code": code},
    )
    db.commit()
    return AcknowledgeOut(
        code=code, acknowledged=True, acknowledged_at=now,
    )

# END OF FILE
