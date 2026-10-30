"""Payroll settings endpoints (Chapter 4, Bundle 003b).

GET /payroll/settings  - current settings, defaults when no row exists
PATCH /payroll/settings - create or update the singleton row

age_reference_date (E6) and sdl_applies (E4) are required before first
finalise; payroll finalisation refuses if they are unset. net_pay_floor
(D14) defaults to 0.00.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_settings_schemas import (
    PayrollSettingsOut,
    PayrollSettingsPatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.services.payroll_audit import write_audit

router = APIRouter(prefix="/payroll/settings", tags=["payroll-settings"])

_DEFAULT_NET_PAY_FLOOR = Decimal("0.00")


def _to_out(row: PayrollSettings | None) -> PayrollSettingsOut:
    if row is None:
        return PayrollSettingsOut(
            age_reference_date=None,
            sdl_applies=None,
            net_pay_floor=_DEFAULT_NET_PAY_FLOOR,
            row_version=0,
        )
    return PayrollSettingsOut(
        age_reference_date=row.age_reference_date,
        sdl_applies=row.sdl_applies,
        net_pay_floor=row.net_pay_floor,
        row_version=row.row_version,
    )


@router.get("", response_model=PayrollSettingsOut)
def get_payroll_settings(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> PayrollSettingsOut:
    row = db.scalar(select(PayrollSettings).limit(1))
    return _to_out(row)


@router.patch("", response_model=PayrollSettingsOut)
def patch_payroll_settings(
    body: PayrollSettingsPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> PayrollSettingsOut:
    row = db.scalar(select(PayrollSettings).limit(1))
    old_snapshot = None
    if row is None:
        if body.row_version != 0:
            raise AppError(
                "record_changed",
                "Settings do not exist; use row_version=0 to create",
                409,
            )
        row = PayrollSettings(
            id=uuid.uuid4(),
            age_reference_date=None,
            sdl_applies=None,
            net_pay_floor=_DEFAULT_NET_PAY_FLOOR,
            row_version=1,
            updated_by_user_id=getattr(user, "id", None),
        )
        db.add(row)
    else:
        if body.row_version != row.row_version:
            raise AppError(
                "record_changed",
                f"row_version mismatch: sent {body.row_version}, current {row.row_version}",
                409,
            )
        old_snapshot = {
            "age_reference_date": row.age_reference_date,
            "sdl_applies": row.sdl_applies,
            "net_pay_floor": str(row.net_pay_floor),
            "row_version": row.row_version,
        }
        row.row_version += 1
        row.updated_by_user_id = getattr(user, "id", None)

    provided = body.model_fields_set - {"row_version"}
    for field in provided:
        setattr(row, field, getattr(body, field))
    if row.net_pay_floor is None:
        row.net_pay_floor = _DEFAULT_NET_PAY_FLOOR

    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_settings",
        entity_id=row.id,
        action="update",
        old_value=old_snapshot,
        new_value={
            "age_reference_date": row.age_reference_date,
            "sdl_applies": row.sdl_applies,
            "net_pay_floor": str(row.net_pay_floor),
            "row_version": row.row_version,
        },
    )
    db.commit()
    return _to_out(row)

# END OF FILE
