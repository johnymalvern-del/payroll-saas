"""Leave type CRUD (Chapter 3, 3B.1).

Permissions:
  - GET*  : LEAVE_APPROVE OR SELF_VIEW (inline OR check, matches pay_history
            pattern)
  - POST / PATCH / deactivate / reactivate : USER_MANAGE (HR + payroll_admin)

Rules:
  - code is stored lowercase, stripped; unique case-insensitive.
  - code is immutable on PATCH (not accepted in LeaveTypePatch).
  - accrual_method='annual' or 'fixed' requires accrual_amount.
  - allow_negative=True requires accrual_method != 'none'.
  - max_carryover not allowed when cycle='fixed'.
  - deactivate refuses 409 leave_type_in_use when any LeaveBalance rows
    reference the type.
  - approval_chain defaults to ["manager", "hr"] per amendment 1.
  - unit='hour' is accepted on the type (schema allows); request-side
    refusal (422 unit_not_supported_yet) lands in L2.

Errors:
  duplicate_code              - code collision (case-insensitive)
  accrual_amount_required     - annual/fixed missing amount
  negative_requires_accrual   - allow_negative with method='none'
  carryover_not_allowed_on_fixed - max_carryover with cycle='fixed'
  leave_type_in_use           - balances reference the type (deactivate)
  record_changed              - row_version mismatch on PATCH
  not_found                   - unknown id
  forbidden                   - caller lacks both LEAVE_APPROVE and SELF_VIEW
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select

from app.api.deps import TenantDbDep
from app.api.v1.leave_types_schemas import (
    LeaveTypeIn,
    LeaveTypeListOut,
    LeaveTypeOut,
    LeaveTypePatch,
)
from app.core.auth_deps import get_current_user
from app.core.errors import AppError
from app.core.permissions import Permission, check_permission, require_permission
from app.db.tenant.models.leave import LeaveBalance, LeaveType
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/leave/types", tags=["leave-types"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _not_found() -> AppError:
    return AppError("not_found", "Leave type not found", 404)


def _to_out(row: LeaveType) -> LeaveTypeOut:
    return LeaveTypeOut.model_validate(row)


def _encode_cursor(created_at: datetime, type_id: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(type_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        ts = datetime.fromisoformat(payload["c"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, uuid.UUID(payload["i"])
    except Exception:
        raise AppError(
            "invalid_cursor", "The pagination cursor is malformed", 400
        ) from None


def _require_read_or_view(user: Any) -> None:
    if check_permission(user, Permission.LEAVE_APPROVE):
        return
    if check_permission(user, Permission.SELF_VIEW):
        return
    raise AppError(
        "forbidden",
        "Not permitted to view leave types",
        status.HTTP_403_FORBIDDEN,
    )


def _validate_business_rules(
    *,
    accrual_method: str | None,
    accrual_amount,
    cycle: str | None,
    max_carryover,
    allow_negative: bool | None,
) -> None:
    if accrual_method in ("annual", "fixed") and accrual_amount is None:
        raise AppError(
            "accrual_amount_required",
            f"accrual_method={accrual_method!r} requires accrual_amount",
            422,
        )
    if allow_negative is True and accrual_method == "none":
        raise AppError(
            "negative_requires_accrual",
            "allow_negative=True requires accrual_method != 'none'",
            422,
        )
    if max_carryover is not None and cycle == "fixed":
        raise AppError(
            "carryover_not_allowed_on_fixed",
            "max_carryover is not allowed when cycle='fixed'",
            422,
        )


@router.get("", response_model=LeaveTypeListOut)
def list_leave_types(
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
    is_active: bool | None = Query(None),
    unit: str | None = Query(None),
    paid: bool | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> LeaveTypeListOut:
    _require_read_or_view(user)

    q = select(LeaveType)
    if is_active is None:
        q = q.where(LeaveType.is_active.is_(True))
    else:
        q = q.where(LeaveType.is_active.is_(is_active))
    if unit is not None:
        q = q.where(LeaveType.unit == unit)
    if paid is not None:
        q = q.where(LeaveType.paid.is_(paid))

    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(
            or_(
                LeaveType.created_at > ts,
                (LeaveType.created_at == ts) & (LeaveType.id > cid),
            )
        )

    q = q.order_by(
        LeaveType.created_at.asc(), LeaveType.id.asc()
    ).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return LeaveTypeListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/{type_id}", response_model=LeaveTypeOut)
def get_leave_type(
    type_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveTypeOut:
    _require_read_or_view(user)
    row = db.get(LeaveType, type_id)
    if row is None:
        raise _not_found()
    return _to_out(row)


@router.post(
    "", response_model=LeaveTypeOut, status_code=status.HTTP_201_CREATED
)
def create_leave_type(
    payload: LeaveTypeIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> LeaveTypeOut:
    _validate_business_rules(
        accrual_method=payload.accrual_method,
        accrual_amount=payload.accrual_amount,
        cycle=payload.cycle,
        max_carryover=payload.max_carryover,
        allow_negative=payload.allow_negative,
    )

    code = payload.code.strip().lower()
    dup = db.scalar(
        select(LeaveType).where(func.lower(LeaveType.code) == code)
    )
    if dup is not None:
        raise AppError(
            "duplicate_code",
            f"A leave type with code '{code}' already exists",
            409,
        )

    row = LeaveType(
        name=payload.name.strip(),
        code=code,
        unit=payload.unit,
        paid=payload.paid,
        accrual_method=payload.accrual_method,
        accrual_amount=payload.accrual_amount,
        cycle=payload.cycle,
        requires_approval=payload.requires_approval,
        requires_document_after_days=payload.requires_document_after_days,
        allow_negative=payload.allow_negative,
        max_carryover=payload.max_carryover,
        approval_chain=list(payload.approval_chain),
        requires_payroll_admin_final=payload.requires_payroll_admin_final,
        is_active=True,
        row_version=1,
    )
    db.add(row)
    db.flush()

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_type",
        entity_id=str(row.id),
        action="leave_type.create",
        old_value=None,
        new_value=redact_for_audit(_to_out(row).model_dump(mode="json")),
    ))
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.patch("/{type_id}", response_model=LeaveTypeOut)
def patch_leave_type(
    type_id: uuid.UUID,
    payload: LeaveTypePatch,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> LeaveTypeOut:
    row = db.get(LeaveType, type_id)
    if row is None:
        raise _not_found()

    if row.row_version != payload.row_version:
        raise AppError(
            "record_changed",
            f"Leave type has changed (current {row.row_version}); reload and retry",
            409,
            {"current_row_version": row.row_version},
        )

    supplied = payload.model_dump(exclude_unset=True)
    supplied.pop("row_version", None)
    supplied.pop("code", None)  # code is immutable; ignore if ever supplied

    proposed = {
        "accrual_method": supplied.get("accrual_method", row.accrual_method),
        "accrual_amount": supplied.get("accrual_amount", row.accrual_amount),
        "cycle": supplied.get("cycle", row.cycle),
        "max_carryover": supplied.get("max_carryover", row.max_carryover),
        "allow_negative": supplied.get("allow_negative", row.allow_negative),
    }
    _validate_business_rules(**proposed)

    old_snapshot = _to_out(row).model_dump(mode="json")
    for k, v in supplied.items():
        if k == "approval_chain" and v is not None:
            setattr(row, "approval_chain", list(v))
        else:
            setattr(row, k, v)
    row.row_version = row.row_version + 1
    db.flush()

    new_snapshot = _to_out(row).model_dump(mode="json")
    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_type",
        entity_id=str(row.id),
        action="leave_type.update",
        old_value=redact_for_audit(old_snapshot),
        new_value=redact_for_audit(new_snapshot),
    ))
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/{type_id}/deactivate", response_model=LeaveTypeOut)
def deactivate_leave_type(
    type_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> LeaveTypeOut:
    row = db.get(LeaveType, type_id)
    if row is None:
        raise _not_found()

    balance_count = int(db.scalar(
        select(func.count()).select_from(LeaveBalance).where(
            LeaveBalance.leave_type_id == type_id
        )
    ) or 0)
    if balance_count > 0:
        raise AppError(
            "leave_type_in_use",
            f"{balance_count} leave balance row(s) reference this type; "
            f"cannot deactivate",
            409,
            {"balances": balance_count},
        )

    old_snapshot = _to_out(row).model_dump(mode="json")
    row.is_active = False
    row.row_version = row.row_version + 1
    db.flush()
    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_type",
        entity_id=str(row.id),
        action="leave_type.deactivate",
        old_value=redact_for_audit(old_snapshot),
        new_value=redact_for_audit(_to_out(row).model_dump(mode="json")),
    ))
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/{type_id}/reactivate", response_model=LeaveTypeOut)
def reactivate_leave_type(
    type_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> LeaveTypeOut:
    row = db.get(LeaveType, type_id)
    if row is None:
        raise _not_found()

    old_snapshot = _to_out(row).model_dump(mode="json")
    row.is_active = True
    row.row_version = row.row_version + 1
    db.flush()
    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_type",
        entity_id=str(row.id),
        action="leave_type.reactivate",
        old_value=redact_for_audit(old_snapshot),
        new_value=redact_for_audit(_to_out(row).model_dump(mode="json")),
    ))
    db.commit()
    db.refresh(row)
    return _to_out(row)