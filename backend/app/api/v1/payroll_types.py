"""Earning and deduction type configuration (Chapter 4, Bundle 003b).

Reads are PAYROLL_PREVIEW (hr + payroll_admin). Writes are PAYROLL_FINALISE
(payroll_admin only), per F3: config that affects payroll amount is
payroll_admin.

Earning types drive the payroll engine's line generation; deduction types
drive the deduction pipeline. is_system rows are seeded by later bundles and
cannot be deleted via the API.
"""
from __future__ import annotations

import base64
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_types_schemas import (
    DeductionTypeIn,
    DeductionTypeListOut,
    DeductionTypeOut,
    DeductionTypePatch,
    EarningTypeIn,
    EarningTypeListOut,
    EarningTypeOut,
    EarningTypePatch,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.pay import DeductionType, EarningType
from app.services.payroll_audit import write_audit

router = APIRouter(prefix="/payroll", tags=["payroll-types"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _encode_uuid_cursor(uid: uuid.UUID) -> str:
    raw = json.dumps({"i": str(uid)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_uuid_cursor(cursor: str) -> uuid.UUID:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        return uuid.UUID(json.loads(raw)["i"])
    except Exception:
        raise AppError("invalid_cursor", "The pagination cursor is malformed", 400) from None


# ---------------------------------------------------------------------------
# Earning types
# ---------------------------------------------------------------------------

@router.get("/earning-types", response_model=EarningTypeListOut)
def list_earning_types(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
    active_only: bool = Query(True),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> EarningTypeListOut:
    q = select(EarningType)
    if active_only:
        q = q.where(EarningType.is_active.is_(True))
    if cursor is not None:
        q = q.where(EarningType.id > _decode_uuid_cursor(cursor))
    q = q.order_by(EarningType.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_uuid_cursor(rows[-1].id)
    return EarningTypeListOut(
        items=[EarningTypeOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/earning-types/{type_id}", response_model=EarningTypeOut)
def get_earning_type(
    type_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> EarningTypeOut:
    row = db.scalar(select(EarningType).where(EarningType.id == type_id))
    if row is None:
        raise AppError("not_found", "Earning type not found", 404)
    return EarningTypeOut.model_validate(row)


@router.post("/earning-types", response_model=EarningTypeOut, status_code=201)
def create_earning_type(
    body: EarningTypeIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> EarningTypeOut:
    dup = db.scalar(select(EarningType).where(EarningType.code == body.code))
    if dup is not None:
        raise AppError("code_taken", f"earning_type code {body.code!r} already exists", 409)
    row = EarningType(
        id=uuid.uuid4(),
        name=body.name,
        code=body.code,
        calc_method=body.calc_method,
        frequency=body.frequency,
        is_taxable=body.is_taxable,
        counts_for_uif=body.counts_for_uif,
        counts_for_sdl=body.counts_for_sdl,
        ledger_account=body.ledger_account,
        proration_rule=body.proration_rule,
        eligibility_rule=body.eligibility_rule,
        is_system=False,
        is_active=True,
    )
    db.add(row)
    db.flush()
    write_audit(
        db, user,
        entity_type="earning_type", entity_id=row.id, action="create",
        new_value={"code": row.code, "name": row.name, "calc_method": row.calc_method,
                   "frequency": row.frequency, "is_taxable": row.is_taxable},
    )
    db.commit()
    return EarningTypeOut.model_validate(row)


@router.patch("/earning-types/{type_id}", response_model=EarningTypeOut)
def patch_earning_type(
    type_id: uuid.UUID,
    body: EarningTypePatch,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> EarningTypeOut:
    row = db.scalar(select(EarningType).where(EarningType.id == type_id))
    if row is None:
        raise AppError("not_found", "Earning type not found", 404)
    if row.is_system:
        raise AppError("system_row", "System earning types cannot be modified via API", 409)
    if body.row_version != row.row_version:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {body.row_version}, current {row.row_version}",
            409,
        )
    old_snapshot = {
        "name": row.name, "calc_method": row.calc_method, "frequency": row.frequency,
        "is_taxable": row.is_taxable, "counts_for_uif": row.counts_for_uif,
        "counts_for_sdl": row.counts_for_sdl, "is_active": row.is_active,
        "row_version": row.row_version,
    }
    provided = body.model_fields_set - {"row_version"}
    for field in provided:
        setattr(row, field, getattr(body, field))
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="earning_type", entity_id=row.id, action="update",
        old_value=old_snapshot,
        new_value={
            "name": row.name, "calc_method": row.calc_method, "frequency": row.frequency,
            "is_taxable": row.is_taxable, "counts_for_uif": row.counts_for_uif,
            "counts_for_sdl": row.counts_for_sdl, "is_active": row.is_active,
            "row_version": row.row_version,
        },
    )
    db.commit()
    return EarningTypeOut.model_validate(row)


@router.post("/earning-types/{type_id}/deactivate", response_model=EarningTypeOut)
def deactivate_earning_type(
    type_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
    row_version: int = Query(...),
) -> EarningTypeOut:
    row = db.scalar(select(EarningType).where(EarningType.id == type_id))
    if row is None:
        raise AppError("not_found", "Earning type not found", 404)
    if row.is_system:
        raise AppError("system_row", "System earning types cannot be deactivated via API", 409)
    if row_version != row.row_version:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {row_version}, current {row.row_version}",
            409,
        )
    row.is_active = False
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="earning_type", entity_id=row.id, action="deactivate",
        old_value={"is_active": True}, new_value={"is_active": False},
    )
    db.commit()
    return EarningTypeOut.model_validate(row)


# ---------------------------------------------------------------------------
# Deduction types
# ---------------------------------------------------------------------------

@router.get("/deduction-types", response_model=DeductionTypeListOut)
def list_deduction_types(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
    active_only: bool = Query(True),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> DeductionTypeListOut:
    q = select(DeductionType)
    if active_only:
        q = q.where(DeductionType.is_active.is_(True))
    if cursor is not None:
        q = q.where(DeductionType.id > _decode_uuid_cursor(cursor))
    q = q.order_by(DeductionType.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_uuid_cursor(rows[-1].id)
    return DeductionTypeListOut(
        items=[DeductionTypeOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/deduction-types/{type_id}", response_model=DeductionTypeOut)
def get_deduction_type(
    type_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> DeductionTypeOut:
    row = db.scalar(select(DeductionType).where(DeductionType.id == type_id))
    if row is None:
        raise AppError("not_found", "Deduction type not found", 404)
    return DeductionTypeOut.model_validate(row)


@router.post("/deduction-types", response_model=DeductionTypeOut, status_code=201)
def create_deduction_type(
    body: DeductionTypeIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> DeductionTypeOut:
    dup = db.scalar(select(DeductionType).where(DeductionType.code == body.code))
    if dup is not None:
        raise AppError("code_taken", f"deduction_type code {body.code!r} already exists", 409)
    row = DeductionType(
        id=uuid.uuid4(),
        name=body.name,
        code=body.code,
        category=body.category,
        priority=body.priority,
        is_pre_tax=body.is_pre_tax,
        is_system=False,
        is_active=True,
    )
    db.add(row)
    db.flush()
    write_audit(
        db, user,
        entity_type="deduction_type", entity_id=row.id, action="create",
        new_value={"code": row.code, "name": row.name, "category": row.category,
                   "priority": row.priority, "is_pre_tax": row.is_pre_tax},
    )
    db.commit()
    return DeductionTypeOut.model_validate(row)


@router.patch("/deduction-types/{type_id}", response_model=DeductionTypeOut)
def patch_deduction_type(
    type_id: uuid.UUID,
    body: DeductionTypePatch,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> DeductionTypeOut:
    row = db.scalar(select(DeductionType).where(DeductionType.id == type_id))
    if row is None:
        raise AppError("not_found", "Deduction type not found", 404)
    if row.is_system:
        raise AppError("system_row", "System deduction types cannot be modified via API", 409)
    if body.row_version != row.row_version:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {body.row_version}, current {row.row_version}",
            409,
        )
    old_snapshot = {
        "name": row.name, "category": row.category, "priority": row.priority,
        "is_pre_tax": row.is_pre_tax, "is_active": row.is_active,
        "row_version": row.row_version,
    }
    provided = body.model_fields_set - {"row_version"}
    for field in provided:
        setattr(row, field, getattr(body, field))
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="deduction_type", entity_id=row.id, action="update",
        old_value=old_snapshot,
        new_value={
            "name": row.name, "category": row.category, "priority": row.priority,
            "is_pre_tax": row.is_pre_tax, "is_active": row.is_active,
            "row_version": row.row_version,
        },
    )
    db.commit()
    return DeductionTypeOut.model_validate(row)


@router.post("/deduction-types/{type_id}/deactivate", response_model=DeductionTypeOut)
def deactivate_deduction_type(
    type_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
    row_version: int = Query(...),
) -> DeductionTypeOut:
    row = db.scalar(select(DeductionType).where(DeductionType.id == type_id))
    if row is None:
        raise AppError("not_found", "Deduction type not found", 404)
    if row.is_system:
        raise AppError("system_row", "System deduction types cannot be deactivated via API", 409)
    if row_version != row.row_version:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {row_version}, current {row.row_version}",
            409,
        )
    row.is_active = False
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="deduction_type", entity_id=row.id, action="deactivate",
        old_value={"is_active": True}, new_value={"is_active": False},
    )
    db.commit()
    return DeductionTypeOut.model_validate(row)

# END OF FILE
