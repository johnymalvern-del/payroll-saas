'''Public holiday tenant override endpoints (Chapter 2A).'''
from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select, update

from app.api.deps import TenantDbDep
from app.api.v1.public_holidays_schemas import (
    PublicHolidayCreateIn,
    PublicHolidayListOut,
    PublicHolidayOut,
    PublicHolidayPatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.attendance import PublicHolidayTenant
from app.db.tenant.models.organisation import Department, Site
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix='/public-holidays', tags=['public-holidays'])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _to_out(h: PublicHolidayTenant) -> PublicHolidayOut:
    return PublicHolidayOut(id=h.id, holiday_date=h.holiday_date, name=h.name, site_id=h.site_id, department_id=h.department_id, is_working_day_override=h.is_working_day_override, is_active=h.is_active, row_version=h.row_version)


def _encode_cursor(created_at: datetime, hid: uuid.UUID) -> str:
    payload = {'c': created_at.isoformat(), 'i': str(hid)}
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
    return AppError('record_not_found', 'Public holiday not found', 404)


def _validate_scope_refs(db: Any, site_id, department_id) -> None:
    if site_id is not None and db.get(Site, site_id) is None:
        raise AppError('invalid_site', 'site_id does not exist', 400)
    if department_id is not None and db.get(Department, department_id) is None:
        raise AppError('invalid_department', 'department_id does not exist', 400)


@router.get('', response_model=PublicHolidayListOut)
def list_public_holidays(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    from_date: date | None = Query(None, alias='from'),
    to_date: date | None = Query(None, alias='to'),
    site_id: uuid.UUID | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    include_inactive: bool = Query(False),
    include_total: bool = Query(False),
) -> PublicHolidayListOut:
    q = select(PublicHolidayTenant)
    if not include_inactive:
        q = q.where(PublicHolidayTenant.is_active.is_(True))
    if from_date is not None:
        q = q.where(PublicHolidayTenant.holiday_date >= from_date)
    if to_date is not None:
        q = q.where(PublicHolidayTenant.holiday_date <= to_date)
    if site_id is not None:
        q = q.where(PublicHolidayTenant.site_id == site_id)
    if department_id is not None:
        q = q.where(PublicHolidayTenant.department_id == department_id)
    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(or_(PublicHolidayTenant.created_at > ts, (PublicHolidayTenant.created_at == ts) & (PublicHolidayTenant.id > cid)))
    q = q.order_by(PublicHolidayTenant.created_at.asc(), PublicHolidayTenant.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)
    total = None
    if include_total:
        tq = select(func.count()).select_from(PublicHolidayTenant)
        if not include_inactive:
            tq = tq.where(PublicHolidayTenant.is_active.is_(True))
        if from_date is not None:
            tq = tq.where(PublicHolidayTenant.holiday_date >= from_date)
        if to_date is not None:
            tq = tq.where(PublicHolidayTenant.holiday_date <= to_date)
        if site_id is not None:
            tq = tq.where(PublicHolidayTenant.site_id == site_id)
        if department_id is not None:
            tq = tq.where(PublicHolidayTenant.department_id == department_id)
        total = int(db.scalar(tq) or 0)
    return PublicHolidayListOut(items=[_to_out(r) for r in rows], next_cursor=next_cursor, total=total)


@router.post('', response_model=PublicHolidayOut, status_code=status.HTTP_201_CREATED)
def create_public_holiday(
    payload: PublicHolidayCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> PublicHolidayOut:
    _validate_scope_refs(db, payload.site_id, payload.department_id)
    h = PublicHolidayTenant(holiday_date=payload.holiday_date, name=payload.name.strip(), site_id=payload.site_id, department_id=payload.department_id, is_working_day_override=payload.is_working_day_override, is_active=True, row_version=1)
    db.add(h)
    db.flush()
    snap = _to_out(h).model_dump(mode='json')
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='public_holiday_tenant', entity_id=str(h.id), action='public_holiday.create', old_value=None, new_value=redact_for_audit(snap)))
    db.commit()
    db.refresh(h)
    return _to_out(h)


@router.patch('/{hid}', response_model=PublicHolidayOut)
def patch_public_holiday(
    hid: uuid.UUID,
    payload: PublicHolidayPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> PublicHolidayOut:
    current = db.get(PublicHolidayTenant, hid)
    if current is None:
        raise _not_found()
    if current.row_version != payload.row_version:
        raise AppError('record_changed', 'Public holiday has changed; reload and retry', 409, {'current_row_version': current.row_version})
    supplied = payload.model_dump(exclude_unset=True)
    if 'name' in supplied and supplied['name'] is not None:
        supplied['name'] = supplied['name'].strip()
    update_fields = {k: v for k, v in supplied.items() if k != 'row_version'}
    if not update_fields:
        return _to_out(current)
    old_snap = _to_out(current).model_dump(mode='json')
    new_version = current.row_version + 1
    stmt = update(PublicHolidayTenant).where(PublicHolidayTenant.id == current.id, PublicHolidayTenant.row_version == payload.row_version).values(**update_fields, row_version=new_version)
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise AppError('record_changed', 'Public holiday changed during this request; reload and retry', 409)
    db.expire_all()
    db.flush()
    refreshed = db.scalar(select(PublicHolidayTenant).where(PublicHolidayTenant.id == current.id))
    new_snap = _to_out(refreshed).model_dump(mode='json')
    if old_snap.get('is_active') and not new_snap.get('is_active'):
        action = 'public_holiday.deactivate'
    elif not old_snap.get('is_active') and new_snap.get('is_active'):
        action = 'public_holiday.reactivate'
    else:
        action = 'public_holiday.update'
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='public_holiday_tenant', entity_id=str(current.id), action=action, old_value=redact_for_audit(old_snap), new_value=redact_for_audit(new_snap)))
    db.commit()
    db.refresh(refreshed)
    return _to_out(refreshed)


@router.delete('/{hid}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_public_holiday(
    hid: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> Response:
    h = db.get(PublicHolidayTenant, hid)
    if h is None:
        raise _not_found()
    if h.holiday_date <= date.today():
        raise AppError('public_holiday_in_use', 'Only future-dated holidays may be deleted; deactivate via PATCH is_active=false', 409, {'holiday_date': h.holiday_date.isoformat()})
    old_snap = _to_out(h).model_dump(mode='json')
    db.delete(h)
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='public_holiday_tenant', entity_id=str(hid), action='public_holiday.delete', old_value=redact_for_audit(old_snap), new_value=None))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# END OF FILE
