"""Payroll settings (Chapter 4 Bundle 003b + Chapter 4H B-4 foundation).

GET requires PAYROLL_PREVIEW. PATCH requires PAYROLL_FINALISE.

Chapter 4H additions:
  - Validate `attendance_earning_map` keys are `<kind>|<day_type>|<tier_or_any>`
    (422 `invalid_attendance_earning_map` otherwise).
  - Validate `unpaid_day_formula_code` and `monthly_hourly_derivation_formula_code`
    are registered in `app.services.payroll_formulas.FORMULA_REGISTRY`
    (422 `unknown_formula` otherwise) — the ack gate is enforced by the
    run itself, this only ensures the name resolves.
  - Audit old/new via `write_audit` (action `payroll_settings.update`).
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
from app.services.payroll_formulas import FORMULA_REGISTRY

router = APIRouter(prefix="/payroll/settings", tags=["payroll-settings"])

_DEFAULT_NET_PAY_FLOOR = Decimal("0.00")

_ALLOWED_KINDS = ("normal", "overtime", "allowance")


def _to_out(row: PayrollSettings | None) -> PayrollSettingsOut:
    if row is None:
        return PayrollSettingsOut(
            age_reference_date=None,
            sdl_applies=None,
            net_pay_floor=_DEFAULT_NET_PAY_FLOOR,
            row_version=0,
            attendance_earning_map={},
            unpaid_day_behaviour=None,
            unpaid_day_formula_code=None,
            public_holiday_unworked_monthly=None,
            public_holiday_paid=None,
            leave_authoritative_source=None,
            monthly_hourly_derivation_formula_code=None,
            leave_earning_for_monthly=None,
            demo_values=False,
        )
    return PayrollSettingsOut.model_validate(row)


def _validate_attendance_map(m: dict[str, str]) -> None:
    if not isinstance(m, dict):
        raise AppError(
            "invalid_attendance_earning_map",
            "attendance_earning_map must be a dict of string -> string",
            422,
        )
    for k, v in m.items():
        if not isinstance(k, str):
            raise AppError(
                "invalid_attendance_earning_map",
                f"key {k!r} must be a string",
                422,
                {"key": str(k)},
            )
        parts = k.split("|")
        if len(parts) != 3:
            raise AppError(
                "invalid_attendance_earning_map",
                f"key {k!r} must be '<kind>|<day_type>|<tier_or_any>'",
                422,
                {"key": k},
            )
        kind = parts[0]
        if kind not in _ALLOWED_KINDS:
            raise AppError(
                "invalid_attendance_earning_map",
                f"key {k!r}: kind must be one of {_ALLOWED_KINDS}",
                422,
                {"key": k, "kind": kind},
            )
        if not isinstance(v, str) or not v:
            raise AppError(
                "invalid_attendance_earning_map",
                f"key {k!r}: value must be a non-empty string",
                422,
                {"key": k},
            )


def _validate_formula_code(field: str, code: str | None) -> None:
    if code is None:
        return
    if code not in FORMULA_REGISTRY:
        raise AppError(
            "unknown_formula",
            f"{field}={code!r} is not in FORMULA_REGISTRY",
            422,
            {"field": field, "code": code},
        )


@router.get("", response_model=PayrollSettingsOut)
def get_payroll_settings(
    db: TenantDbDep,
    _user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> PayrollSettingsOut:
    row = db.scalar(select(PayrollSettings))
    return _to_out(row)


@router.patch("", response_model=PayrollSettingsOut)
def patch_payroll_settings(
    body: PayrollSettingsPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> PayrollSettingsOut:
    row = db.scalar(select(PayrollSettings))
    if row is None:
        row = PayrollSettings(
            id=uuid.uuid4(),
            age_reference_date=None,
            sdl_applies=None,
            net_pay_floor=_DEFAULT_NET_PAY_FLOOR,
            formula_acks={},
            attendance_earning_map={},
            unpaid_day_behaviour=None,
            unpaid_day_formula_code=None,
            public_holiday_unworked_monthly=None,
            public_holiday_paid=None,
            leave_authoritative_source=None,
            monthly_hourly_derivation_formula_code=None,
            leave_earning_for_monthly=None,
            demo_values=False,
            row_version=1,
        )
        db.add(row)
        db.flush()
        old_snapshot = None
    else:
        if body.row_version != row.row_version:
            raise AppError(
                "record_changed",
                f"payroll_settings version mismatch: sent {body.row_version}, "
                f"current {row.row_version}",
                409,
                {"current_row_version": row.row_version},
            )
        old_snapshot = _to_out(row).model_dump(mode="json")

    supplied = body.model_dump(exclude_unset=True)
    supplied.pop("row_version", None)

    if "attendance_earning_map" in supplied and supplied["attendance_earning_map"] is not None:
        _validate_attendance_map(supplied["attendance_earning_map"])

    _validate_formula_code("unpaid_day_formula_code", supplied.get("unpaid_day_formula_code"))
    _validate_formula_code(
        "monthly_hourly_derivation_formula_code",
        supplied.get("monthly_hourly_derivation_formula_code"),
    )

    for k, v in supplied.items():
        setattr(row, k, v)
    row.row_version = row.row_version + 1
    row.updated_by_user_id = getattr(user, "id", None)
    db.flush()

    new_snapshot = _to_out(row).model_dump(mode="json")
    write_audit(
        db,
        user,
        entity_type="payroll_settings",
        entity_id=row.id,
        action="payroll_settings.update",
        old_value=old_snapshot,
        new_value=new_snapshot,
    )
    db.commit()
    db.refresh(row)
    return _to_out(row)
