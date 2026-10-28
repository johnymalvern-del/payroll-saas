'''Work pattern endpoints (Chapter 2A).'''
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import TenantDbDep
from app.api.v1.work_patterns_schemas import (
    WorkPatternCreateIn,
    WorkPatternDayOut,
    WorkPatternDetailOut,
    WorkPatternListOut,
    WorkPatternOut,
    WorkPatternPatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.attendance import (
    EmployeeWorkPattern,
    WorkPattern,
    WorkPatternDay,
)
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix='/work-patterns', tags=['work-patterns'])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _to_out(p: WorkPattern) -> WorkPatternOut:
    return WorkPatternOut(id=p.id, name=p.name, cycle_length_days=p.cycle_length_days, anchor_date=p.anchor_date, is_active=p.is_active, row_version=p.row_version)


def _to_detail(p: WorkPattern) -> WorkPatternDetailOut:
    days = [WorkPatternDayOut(id=d.id, work_pattern_id=d.work_pattern_id, day_index=d.day_index, is_expected=d.is_expected, expected_shift_id=d.expected_shift_id) for d in p.days]
    return WorkPatternDetailOut(id=p.id, name=p.name, cycle_length_days=p.cycle_length_days, anchor_date=p.anchor_date, is_active=p.is_active, row_version=p.row_version, days=days)


def _encode_cursor(created_at: datetime, pid: uuid.UUID) -> str:
    payload = {'c': created_at.isoformat(), 'i': str(pid)}
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
        raise AppError('invalid_cursor', 'The pagination cursor is malformed', 400) from None


def _not_found() -> AppError:
    return AppError('record_not_found', 'Work pattern not found', 404)


def _name_clash(db: Any, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
    stmt = select(WorkPattern.id).where(WorkPattern.name == name.strip())
    if exclude_id is not None:
        stmt = stmt.where(WorkPattern.id != exclude_id)
    return db.scalar(stmt) is not None


def _in_use_counts(db: Any, pid: uuid.UUID) -> dict[str, int]:
    ewp = int(db.scalar(select(func.count()).select_from(EmployeeWorkPattern).where(EmployeeWorkPattern.work_pattern_id == pid)) or 0)
    return {'employee_work_patterns': ewp}


@router.get('', response_model=WorkPatternListOut)
def list_work_patterns(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_inactive: bool = Query(False),
    include_total: bool = Query(False),
) -> WorkPatternListOut:
    q = select(WorkPattern)
    if not include_inactive:
        q = q.where(WorkPattern.is_active.is_(True))
    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(or_(WorkPattern.created_at > ts, (WorkPattern.created_at == ts) & (WorkPattern.id > cid)))
    q = q.order_by(WorkPattern.created_at.asc(), WorkPattern.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)
    total = None
    if include_total:
        tq = select(func.count()).select_from(WorkPattern)
        if not include_inactive:
            tq = tq.where(WorkPattern.is_active.is_(True))
        total = int(db.scalar(tq) or 0)
    return WorkPatternListOut(items=[_to_out(r) for r in rows], next_cursor=next_cursor, total=total)


@router.get('/{pattern_id}', response_model=WorkPatternDetailOut)
def get_work_pattern(
    pattern_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> WorkPatternDetailOut:
    p = db.scalar(select(WorkPattern).where(WorkPattern.id == pattern_id).options(selectinload(WorkPattern.days)))
    if p is None:
        raise _not_found()
    return _to_detail(p)


@router.post('', response_model=WorkPatternDetailOut, status_code=status.HTTP_201_CREATED)
def create_work_pattern(
    payload: WorkPatternCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> WorkPatternDetailOut:
    if _name_clash(db, payload.name):
        raise AppError('duplicate_name', 'A work pattern with this name already exists', 409)
    for d in payload.days:
        if d.expected_shift_id is not None:
            from app.db.tenant.models.attendance import Shift
            if db.get(Shift, d.expected_shift_id) is None:
                raise AppError('invalid_expected_shift', 'expected_shift_id does not exist', 400)
    p = WorkPattern(name=payload.name.strip(), cycle_length_days=payload.cycle_length_days, anchor_date=payload.anchor_date, is_active=True, row_version=1)
    db.add(p)
    db.flush()
    for d in payload.days:
        db.add(WorkPatternDay(work_pattern_id=p.id, day_index=d.day_index, is_expected=d.is_expected, expected_shift_id=d.expected_shift_id))
    db.flush()
    db.refresh(p)
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='work_pattern', entity_id=str(p.id), action='work_pattern.create', old_value=None, new_value=redact_for_audit(_to_detail(p).model_dump(mode='json'))))
    db.commit()
    p2 = db.scalar(select(WorkPattern).where(WorkPattern.id == p.id).options(selectinload(WorkPattern.days)))
    return _to_detail(p2)


@router.patch('/{pattern_id}', response_model=WorkPatternDetailOut)
def patch_work_pattern(
    pattern_id: uuid.UUID,
    payload: WorkPatternPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> WorkPatternDetailOut:
    p = db.scalar(select(WorkPattern).where(WorkPattern.id == pattern_id).options(selectinload(WorkPattern.days)))
    if p is None:
        raise _not_found()
    if p.row_version != payload.row_version:
        raise AppError('record_changed', 'Work pattern has changed; reload and retry', 409, {'current_row_version': p.row_version})
    supplied = payload.model_dump(exclude_unset=True)
    if 'name' in supplied and supplied['name'] is not None:
        supplied['name'] = supplied['name'].strip()
        if _name_clash(db, supplied['name'], exclude_id=p.id):
            raise AppError('duplicate_name', 'A work pattern with this name already exists', 409)
    new_cycle = supplied.get('cycle_length_days', p.cycle_length_days)
    if 'days' in supplied and supplied['days'] is not None:
        got = [d['day_index'] for d in supplied['days']]
        if set(got) != set(range(new_cycle)):
            raise AppError('invalid_days', 'days must cover 0..N-1', 400)
        from app.db.tenant.models.attendance import Shift
        for d in supplied['days']:
            if d.get('expected_shift_id') is not None and db.get(Shift, d['expected_shift_id']) is None:
                raise AppError('invalid_expected_shift', 'expected_shift_id does not exist', 400)
        for old in list(p.days):
            db.delete(old)
        db.flush()
        for d in supplied['days']:
            db.add(WorkPatternDay(work_pattern_id=p.id, day_index=d['day_index'], is_expected=d['is_expected'], expected_shift_id=d.get('expected_shift_id')))
        del supplied['days']
    for k in ('name', 'cycle_length_days', 'anchor_date', 'is_active'):
        if k in supplied and supplied[k] is not None:
            setattr(p, k, supplied[k])
    p.row_version = p.row_version + 1
    db.flush()
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='work_pattern', entity_id=str(p.id), action='work_pattern.update', old_value=None, new_value=redact_for_audit(_to_detail(p).model_dump(mode='json'))))
    db.commit()
    db.expire_all()
    p2 = db.scalar(select(WorkPattern).where(WorkPattern.id == p.id).options(selectinload(WorkPattern.days)))
    return _to_detail(p2)


@router.delete('/{pattern_id}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_work_pattern(
    pattern_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> Response:
    p = db.get(WorkPattern, pattern_id)
    if p is None:
        raise _not_found()
    counts = _in_use_counts(db, pattern_id)
    if sum(counts.values()) > 0:
        raise AppError('work_pattern_in_use', 'Work pattern is referenced; deactivate via PATCH is_active=false', 409, counts)
    old_snap = _to_detail(p).model_dump(mode='json') if hasattr(p, 'days') else _to_out(p).model_dump(mode='json')
    db.delete(p)
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='work_pattern', entity_id=str(pattern_id), action='work_pattern.delete', old_value=redact_for_audit(old_snap), new_value=None))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# END OF FILE
