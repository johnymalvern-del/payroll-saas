'''Shift CRUD endpoints (Chapter 2A).'''
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select, update

from app.api.deps import TenantDbDep
from app.api.v1.shifts_schemas import (
    ShiftCreateIn,
    ShiftListOut,
    ShiftOut,
    ShiftPatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.attendance import Shift, ShiftRateRule, WorkPatternDay
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix='/shifts', tags=['shifts'])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _to_out(s: Shift) -> ShiftOut:
    return ShiftOut(
        id=s.id, name=s.name, start_time=s.start_time,
        length_minutes=s.length_minutes,
        unpaid_break_minutes=s.unpaid_break_minutes,
        paid_break_minutes=s.paid_break_minutes,
        grace_late_minutes=s.grace_late_minutes,
        grace_early_minutes=s.grace_early_minutes,
        rounding_minutes=s.rounding_minutes,
        rounding_mode=s.rounding_mode,
        min_overtime_minutes=s.min_overtime_minutes,
        overtime_requires_approval=s.overtime_requires_approval,
        max_shift_minutes=s.max_shift_minutes,
        match_tolerance_minutes=s.match_tolerance_minutes,
        salaried_premium_mode=s.salaried_premium_mode,
        is_active=s.is_active, row_version=s.row_version,
    )


def _encode_cursor(created_at: datetime, shift_id: uuid.UUID) -> str:
    payload = {'c': created_at.isoformat(), 'i': str(shift_id)}
    raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + '=' * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8')
        payload = json.loads(raw)
        ts = datetime.fromisoformat(payload['c'])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, uuid.UUID(payload['i'])
    except Exception:
        raise AppError('invalid_cursor', 'The pagination cursor is malformed', status.HTTP_400_BAD_REQUEST) from None


def _not_found() -> AppError:
    return AppError('record_not_found', 'Shift not found', status.HTTP_404_NOT_FOUND)


def _name_clash(db: Any, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
    stmt = select(Shift.id).where(
        func.lower(func.btrim(Shift.name)) == name.strip().lower(),
        Shift.is_active.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(Shift.id != exclude_id)
    return db.scalar(stmt) is not None


def _in_use_counts(db: Any, shift_id: uuid.UUID) -> dict[str, int]:
    rules = int(db.scalar(select(func.count()).select_from(ShiftRateRule).where(ShiftRateRule.shift_id == shift_id)) or 0)
    wpd = int(db.scalar(select(func.count()).select_from(WorkPatternDay).where(WorkPatternDay.expected_shift_id == shift_id)) or 0)
    emps = int(db.scalar(select(func.count()).select_from(Employee).where(Employee.default_shift_id == shift_id)) or 0)
    return {'rate_rules': rules, 'work_pattern_days': wpd, 'employees': emps}


@router.get('', response_model=ShiftListOut)
def list_shifts(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_inactive: bool = Query(False),
    include_total: bool = Query(False),
) -> ShiftListOut:
    q = select(Shift)
    if not include_inactive:
        q = q.where(Shift.is_active.is_(True))
    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(or_(Shift.created_at > ts, (Shift.created_at == ts) & (Shift.id > cid)))
    q = q.order_by(Shift.created_at.asc(), Shift.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)
    total = None
    if include_total:
        tq = select(func.count()).select_from(Shift)
        if not include_inactive:
            tq = tq.where(Shift.is_active.is_(True))
        total = int(db.scalar(tq) or 0)
    return ShiftListOut(items=[_to_out(r) for r in rows], next_cursor=next_cursor, total=total)

@router.post('', response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(
    payload: ShiftCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> ShiftOut:
    if payload.max_shift_minutes <= payload.length_minutes:
        raise AppError('invalid_max_shift', 'max_shift_minutes must be greater than length_minutes', status.HTTP_400_BAD_REQUEST)
    if _name_clash(db, payload.name):
        raise AppError('duplicate_name', 'A shift with this name already exists', status.HTTP_409_CONFLICT)
    shift = Shift(
        name=payload.name.strip(), start_time=payload.start_time,
        length_minutes=payload.length_minutes,
        unpaid_break_minutes=payload.unpaid_break_minutes,
        paid_break_minutes=payload.paid_break_minutes,
        grace_late_minutes=payload.grace_late_minutes,
        grace_early_minutes=payload.grace_early_minutes,
        rounding_minutes=payload.rounding_minutes,
        rounding_mode=payload.rounding_mode,
        min_overtime_minutes=payload.min_overtime_minutes,
        overtime_requires_approval=payload.overtime_requires_approval,
        max_shift_minutes=payload.max_shift_minutes,
        match_tolerance_minutes=payload.match_tolerance_minutes,
        salaried_premium_mode=payload.salaried_premium_mode,
        is_active=True, row_version=1,
    )
    db.add(shift)
    db.flush()
    snap = _to_out(shift).model_dump(mode='json')
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user,'id',None), actor_role=getattr(user,'role',None), entity_type='shift', entity_id=str(shift.id), action='shift.create', old_value=None, new_value=redact_for_audit(snap)))
    db.commit()
    db.refresh(shift)
    return _to_out(shift)


@router.get('/{shift_id}', response_model=ShiftOut)
def get_shift(
    shift_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> ShiftOut:
    s = db.get(Shift, shift_id)
    if s is None:
        raise _not_found()
    return _to_out(s)


@router.patch('/{shift_id}', response_model=ShiftOut)
def patch_shift(
    shift_id: uuid.UUID,
    payload: ShiftPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> ShiftOut:
    current = db.get(Shift, shift_id)
    if current is None:
        raise _not_found()
    if current.row_version != payload.row_version:
        raise AppError('record_changed', 'Shift has changed; reload and retry', status.HTTP_409_CONFLICT, {'current_row_version': current.row_version})
    supplied = payload.model_dump(exclude_unset=True)
    if 'name' in supplied and supplied['name'] is not None:
        supplied['name'] = supplied['name'].strip()
        new_name = supplied['name']
        if _name_clash(db, new_name, exclude_id=current.id):
            raise AppError('duplicate_name', 'A shift with this name already exists', status.HTTP_409_CONFLICT)
    prosp_len = supplied.get('length_minutes', current.length_minutes)
    prosp_max = supplied.get('max_shift_minutes', current.max_shift_minutes)
    if prosp_max <= prosp_len:
        raise AppError('invalid_max_shift', 'max_shift_minutes must be greater than length_minutes', status.HTTP_400_BAD_REQUEST)
    update_fields = {k: v for k, v in supplied.items() if k != 'row_version'}
    if not update_fields:
        return _to_out(current)
    old_snap = _to_out(current).model_dump(mode='json')
    new_version = current.row_version + 1
    stmt = update(Shift).where(Shift.id == current.id, Shift.row_version == payload.row_version).values(**update_fields, row_version=new_version)
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise AppError('record_changed', 'Shift changed during this request; reload and retry', status.HTTP_409_CONFLICT)
    db.expire_all()
    db.flush()
    refreshed = db.scalar(select(Shift).where(Shift.id == current.id))
    assert refreshed is not None
    new_snap = _to_out(refreshed).model_dump(mode='json')
    if old_snap.get('is_active') and not new_snap.get('is_active'):
        action = 'shift.deactivate'
    elif not old_snap.get('is_active') and new_snap.get('is_active'):
        action = 'shift.reactivate'
    else:
        action = 'shift.update'
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user,'id',None), actor_role=getattr(user,'role',None), entity_type='shift', entity_id=str(current.id), action=action, old_value=redact_for_audit(old_snap), new_value=redact_for_audit(new_snap)))
    db.commit()
    db.refresh(refreshed)
    return _to_out(refreshed)


@router.delete('/{shift_id}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_shift(
    shift_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> Response:
    s = db.get(Shift, shift_id)
    if s is None:
        raise _not_found()
    counts = _in_use_counts(db, shift_id)
    total_refs = sum(counts.values())
    if total_refs > 0:
        raise AppError('shift_in_use', 'Shift is referenced; deactivate via PATCH is_active=false', status.HTTP_409_CONFLICT, counts)
    old_snap = _to_out(s).model_dump(mode='json')
    db.delete(s)
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user,'id',None), actor_role=getattr(user,'role',None), entity_type='shift', entity_id=str(shift_id), action='shift.delete', old_value=redact_for_audit(old_snap), new_value=None))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# END OF FILE
