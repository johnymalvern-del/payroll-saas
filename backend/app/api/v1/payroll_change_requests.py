"""Payroll change requests (Chapter 4, Bundle 004a-iv-a).

HR submits via PAY_RATE_REQUEST, payroll_admin approves via PAY_RATE_APPROVE.
List/get via PAY_RATE_VIEW (hr, payroll_admin, auditor).
"""
from __future__ import annotations

import base64
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_change_requests_schemas import (
    ChangeRequestListOut,
    ChangeRequestOut,
    ChangeRequestSubmitIn,
    RejectIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.services.payroll_change_request import (
    approve_change_request,
    cancel_change_request,
    reject_change_request,
    submit_change_request,
)

router = APIRouter(prefix="/payroll/change-requests", tags=["payroll-change-requests"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _encode_cursor(uid: uuid.UUID) -> str:
    raw = json.dumps({"i": str(uid)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> uuid.UUID:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        return uuid.UUID(json.loads(raw)["i"])
    except Exception:
        raise AppError("invalid_cursor", "The pagination cursor is malformed", 400) from None


@router.post("", response_model=ChangeRequestOut, status_code=201)
def submit(
    body: ChangeRequestSubmitIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> ChangeRequestOut:
    request = submit_change_request(
        db, user,
        kind=body.kind,
        employee_id=body.employee_id,
        payload=body.payload,
        note=body.note,
    )
    db.commit()
    return ChangeRequestOut.model_validate(request)


@router.get("", response_model=ChangeRequestListOut)
def list_requests(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
    status: str | None = Query(None),
    employee_id: uuid.UUID | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> ChangeRequestListOut:
    q = select(PayrollChangeRequest)
    if status is not None:
        q = q.where(PayrollChangeRequest.status == status)
    if employee_id is not None:
        q = q.where(PayrollChangeRequest.employee_id == employee_id)
    if cursor is not None:
        q = q.where(PayrollChangeRequest.id > _decode_cursor(cursor))
    q = q.order_by(PayrollChangeRequest.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)
    return ChangeRequestListOut(
        items=[ChangeRequestOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/{request_id}", response_model=ChangeRequestOut)
def get_request(
    request_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> ChangeRequestOut:
    row = db.scalar(
        select(PayrollChangeRequest).where(PayrollChangeRequest.id == request_id)
    )
    if row is None:
        raise AppError("not_found", "Change request not found", 404)
    return ChangeRequestOut.model_validate(row)


@router.post("/{request_id}/approve", response_model=ChangeRequestOut)
def approve(
    request_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_APPROVE))],
) -> ChangeRequestOut:
    request, _applied_id = approve_change_request(db, user, request_id)
    db.commit()
    return ChangeRequestOut.model_validate(request)


@router.post("/{request_id}/reject", response_model=ChangeRequestOut)
def reject(
    request_id: uuid.UUID,
    body: RejectIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_APPROVE))],
) -> ChangeRequestOut:
    request = reject_change_request(db, user, request_id, body.note)
    db.commit()
    return ChangeRequestOut.model_validate(request)


@router.post("/{request_id}/cancel", response_model=ChangeRequestOut)
def cancel(
    request_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> ChangeRequestOut:
    request = cancel_change_request(db, user, request_id)
    db.commit()
    return ChangeRequestOut.model_validate(request)

# END OF FILE
