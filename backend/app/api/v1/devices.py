'''Device endpoints (Chapter 2A).'''
from __future__ import annotations

import base64
import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select, update

from app.api.deps import TenantDbDep
from app.api.v1.device_auth import hash_device_key
from app.api.v1.devices_schemas import (
    DeviceCreateIn,
    DeviceCreateOut,
    DeviceListOut,
    DeviceOut,
    DevicePatchIn,
    DeviceRotateKeyOut,
    _DEVICE_TYPES,
    _STATUSES,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.attendance import Punch
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Site
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix='/devices', tags=['devices'])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _to_out(d: Device) -> DeviceOut:
    return DeviceOut(id=d.id, site_id=d.site_id, name=d.name, device_type=d.device_type, status=d.status, last_seen_at=d.last_seen_at, last_sync_at=d.last_sync_at, pending_punch_count=d.pending_punch_count, allows_code_only=d.allows_code_only, require_photo_for_code=d.require_photo_for_code, software_version=d.software_version, row_version=d.row_version)


def _encode_cursor(created_at: datetime, did: uuid.UUID) -> str:
    payload = {'c': created_at.isoformat(), 'i': str(did)}
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
    return AppError('record_not_found', 'Device not found', 404)


def _generate_key() -> str:
    return secrets.token_hex(32)


@router.get('', response_model=DeviceListOut)
def list_devices(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    site_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias='status'),
    include_total: bool = Query(False),
) -> DeviceListOut:
    q = select(Device)
    if site_id is not None:
        q = q.where(Device.site_id == site_id)
    if status_filter is not None:
        q = q.where(Device.status == status_filter)
    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(or_(Device.created_at > ts, (Device.created_at == ts) & (Device.id > cid)))
    q = q.order_by(Device.created_at.asc(), Device.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)
    total = None
    if include_total:
        tq = select(func.count()).select_from(Device)
        if site_id is not None:
            tq = tq.where(Device.site_id == site_id)
        if status_filter is not None:
            tq = tq.where(Device.status == status_filter)
        total = int(db.scalar(tq) or 0)
    return DeviceListOut(items=[_to_out(r) for r in rows], next_cursor=next_cursor, total=total)


@router.post('', response_model=DeviceCreateOut, status_code=status.HTTP_201_CREATED)
def create_device(
    payload: DeviceCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> DeviceCreateOut:
    if payload.device_type not in _DEVICE_TYPES:
        raise AppError('invalid_device_type', f'device_type must be one of {_DEVICE_TYPES}', 400)
    if db.get(Site, payload.site_id) is None:
        raise AppError('invalid_site', 'site_id does not exist', 400)
    raw = _generate_key()
    device = Device(site_id=payload.site_id, name=payload.name.strip(), device_type=payload.device_type, api_key_hash=hash_device_key(raw), status='active', allows_code_only=payload.allows_code_only, require_photo_for_code=payload.require_photo_for_code, software_version=payload.software_version, pending_punch_count=0, row_version=1)
    db.add(device)
    db.flush()
    snap = _to_out(device).model_dump(mode='json')
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='device', entity_id=str(device.id), action='device.create', old_value=None, new_value=redact_for_audit(snap)))
    db.commit()
    db.refresh(device)
    out = _to_out(device)
    return DeviceCreateOut(**out.model_dump(), api_key=raw)


@router.get('/{device_id}', response_model=DeviceOut)
def get_device(
    device_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> DeviceOut:
    d = db.get(Device, device_id)
    if d is None:
        raise _not_found()
    return _to_out(d)


@router.patch('/{device_id}', response_model=DeviceOut)
def patch_device(
    device_id: uuid.UUID,
    payload: DevicePatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> DeviceOut:
    current = db.get(Device, device_id)
    if current is None:
        raise _not_found()
    if current.row_version != payload.row_version:
        raise AppError('record_changed', 'Device has changed; reload and retry', 409, {'current_row_version': current.row_version})
    supplied = payload.model_dump(exclude_unset=True)
    if 'status' in supplied and supplied['status'] is not None and supplied['status'] not in _STATUSES:
        raise AppError('invalid_status', f'status must be one of {_STATUSES}', 400)
    if 'site_id' in supplied and supplied['site_id'] is not None and db.get(Site, supplied['site_id']) is None:
        raise AppError('invalid_site', 'site_id does not exist', 400)
    if 'name' in supplied and supplied['name'] is not None:
        supplied['name'] = supplied['name'].strip()
    update_fields = {k: v for k, v in supplied.items() if k != 'row_version'}
    if not update_fields:
        return _to_out(current)
    old_snap = _to_out(current).model_dump(mode='json')
    new_version = current.row_version + 1
    stmt = update(Device).where(Device.id == current.id, Device.row_version == payload.row_version).values(**update_fields, row_version=new_version)
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise AppError('record_changed', 'Device changed during this request; reload and retry', 409)
    db.expire_all()
    db.flush()
    refreshed = db.scalar(select(Device).where(Device.id == current.id))
    new_snap = _to_out(refreshed).model_dump(mode='json')
    action = 'device.status_change' if 'status' in update_fields else 'device.update'
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='device', entity_id=str(current.id), action=action, old_value=redact_for_audit(old_snap), new_value=redact_for_audit(new_snap)))
    db.commit()
    db.refresh(refreshed)
    return _to_out(refreshed)


@router.post('/{device_id}/rotate-key', response_model=DeviceRotateKeyOut)
def rotate_device_key(
    device_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> DeviceRotateKeyOut:
    d = db.get(Device, device_id)
    if d is None:
        raise _not_found()
    old_hash_prefix = d.api_key_hash[:8]
    raw = _generate_key()
    d.api_key_hash = hash_device_key(raw)
    d.row_version = d.row_version + 1
    db.flush()
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='device', entity_id=str(device_id), action='device.rotate_key', old_value={'api_key_hash_prefix': old_hash_prefix}, new_value={'api_key_hash_prefix': d.api_key_hash[:8]}))
    db.commit()
    return DeviceRotateKeyOut(id=device_id, api_key=raw)


@router.delete('/{device_id}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_device(
    device_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> Response:
    d = db.get(Device, device_id)
    if d is None:
        raise _not_found()
    punch_count = int(db.scalar(select(func.count()).select_from(Punch).where(Punch.device_id == device_id)) or 0)
    if punch_count > 0:
        raise AppError('device_in_use', 'Device has punches; set status=inactive via PATCH instead', 409, {'punches': punch_count})
    old_snap = _to_out(d).model_dump(mode='json')
    db.delete(d)
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='device', entity_id=str(device_id), action='device.delete', old_value=redact_for_audit(old_snap), new_value=None))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# END OF FILE
