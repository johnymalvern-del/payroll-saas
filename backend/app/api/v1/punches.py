"""Punch endpoints (Chapter 2A)."""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import ScannerDep, StorageDep, TenantDbDep, TenantDep
from app.api.v1.device_auth import DeviceDep
from app.api.v1.punch_service import (
    canonical_payload_hash,
    classify_match,
    compute_timing_and_offset,
    decode_and_validate_photo,
    is_clock_gap,
    is_future_time,
    validate_raw_payload,
)
from app.api.v1.punches_schemas import (
    PunchBatchIn,
    PunchBatchItemOut,
    PunchBatchOut,
    PunchIn,
    PunchListOut,
    PunchOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.attendance import Punch
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.scanner.base import VirusScanner
from app.storage.base import Storage

router = APIRouter(prefix='/punches', tags=['punches'])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_BATCH_BODY_MAX_BYTES = 5 * 1024 * 1024
_PHOTO_MAX_BYTES = 300 * 1024
_RAW_PAYLOAD_MAX_BYTES = 8 * 1024


def _to_out(p: Punch) -> PunchOut:
    return PunchOut(
        id=p.id, client_punch_id=p.client_punch_id, employee_id=p.employee_id,
        device_id=p.device_id, site_id=p.site_id,
        server_received_at=p.server_received_at, device_time=p.device_time,
        device_now_at_send=p.device_now_at_send, effective_time=p.effective_time,
        offset_ms=p.offset_ms, method=p.method, match_score=p.match_score,
        liveness_passed=p.liveness_passed, photo_object_key=p.photo_object_key,
        latitude=p.latitude, longitude=p.longitude, status=p.status,
        flags=list(p.flags or []), raw_payload=p.raw_payload, created_at=p.created_at,
    )


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


def _existing_by_client_id(db: Any, device_id: uuid.UUID, cpid: uuid.UUID) -> Punch | None:
    return db.scalar(select(Punch).where(Punch.device_id == device_id, Punch.client_punch_id == cpid))


def _handle_idempotent(db: Any, device_id: uuid.UUID, payload: PunchIn) -> Punch | None:
    existing = _existing_by_client_id(db, device_id, payload.client_punch_id)
    if existing is None:
        return None
    sent_hash = canonical_payload_hash(payload.model_dump())
    if existing.payload_hash != sent_hash:
        raise AppError('punch_uuid_reused', 'client_punch_id already used with different payload', 409)
    return existing


@router.get('', response_model=PunchListOut)
def list_punches(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    employee_id: uuid.UUID | None = Query(None),
    site_id: uuid.UUID | None = Query(None),
    device_id: uuid.UUID | None = Query(None),
    from_time: datetime | None = Query(None, alias='from'),
    to_time: datetime | None = Query(None, alias='to'),
    status_filter: str | None = Query(None, alias='status'),
    include_total: bool = Query(False),
) -> PunchListOut:
    q = select(Punch)
    if employee_id is not None:
        q = q.where(Punch.employee_id == employee_id)
    if site_id is not None:
        q = q.where(Punch.site_id == site_id)
    if device_id is not None:
        q = q.where(Punch.device_id == device_id)
    if from_time is not None:
        q = q.where(Punch.effective_time >= from_time)
    if to_time is not None:
        q = q.where(Punch.effective_time <= to_time)
    if status_filter is not None:
        q = q.where(Punch.status == status_filter)
    q = apply_scope(q, user, db, model=Punch)
    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(or_(Punch.created_at > ts, (Punch.created_at == ts) & (Punch.id > cid)))
    q = q.order_by(Punch.created_at.asc(), Punch.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)
    total = None
    if include_total:
        tq = select(func.count()).select_from(Punch)
        if employee_id is not None:
            tq = tq.where(Punch.employee_id == employee_id)
        if site_id is not None:
            tq = tq.where(Punch.site_id == site_id)
        if device_id is not None:
            tq = tq.where(Punch.device_id == device_id)
        if from_time is not None:
            tq = tq.where(Punch.effective_time >= from_time)
        if to_time is not None:
            tq = tq.where(Punch.effective_time <= to_time)
        if status_filter is not None:
            tq = tq.where(Punch.status == status_filter)
        tq = apply_scope(tq, user, db, model=Punch)
        total = int(db.scalar(tq) or 0)
    return PunchListOut(items=[_to_out(r) for r in rows], next_cursor=next_cursor, total=total)


def _process_punch(
    db: Any,
    device: Any,
    user: Any,
    payload: PunchIn,
    request_id: str | None,
    server_received_at: datetime,
    tenant_crypto: Any,
    storage: Storage,
    scanner: VirusScanner,
) -> tuple[Punch, bool]:
    existing = _handle_idempotent(db, device.id, payload)
    if existing is not None:
        return existing, False
    employee = db.get(Employee, payload.employee_id)
    if employee is None:
        raise AppError('unknown_employee', 'employee_id does not exist', 422)
    validate_raw_payload(payload.raw_payload, _RAW_PAYLOAD_MAX_BYTES)
    photo_bytes = decode_and_validate_photo(payload.photo_base64, _PHOTO_MAX_BYTES)
    if payload.method == 'code':
        if not device.allows_code_only:
            raise AppError('code_not_allowed_here', 'This device does not allow code-only punches', 403)
        if device.require_photo_for_code and photo_bytes is None:
            raise AppError('photo_required', 'This device requires a photo for code-only punches', 400)
    effective_time, offset_ms = compute_timing_and_offset(payload.device_time, payload.device_now_at_send, server_received_at)
    flags: list[str] = []
    status_val = 'accepted'
    if is_future_time(effective_time, server_received_at):
        flags.append('future_time')
        status_val = 'rejected'
    if is_clock_gap(offset_ms, 300):
        flags.append('clock_gap')
    if employee.site_id is not None and device.site_id is not None and employee.site_id != device.site_id:
        flags.append('site_mismatch')
    if employee.status != 'active':
        flags.append('employee_not_active')
        if status_val == 'accepted':
            status_val = 'rejected'
    for f in classify_match(payload.match_score, payload.liveness_passed, 60):
        flags.append(f)
        if status_val == 'accepted':
            status_val = 'low_confidence'
    photo_object_key = None
    if photo_bytes is not None:
        scan_ok = scanner.scan(photo_bytes, filename='punch_photo.jpg')
        if not scan_ok:
            raise AppError('photo_scan_failed', 'Photo failed virus scan', 400)
        key = f'punches/{device.id}/{uuid.uuid4().hex}.jpg'
        storage.put(key, photo_bytes)
        photo_object_key = key
    payload_hash = canonical_payload_hash(payload.model_dump())
    punch = Punch(
        client_punch_id=payload.client_punch_id,
        payload_hash=payload_hash,
        employee_id=payload.employee_id,
        device_id=device.id,
        site_id=device.site_id,
        device_time=payload.device_time,
        device_now_at_send=payload.device_now_at_send,
        effective_time=effective_time,
        offset_ms=offset_ms,
        method=payload.method,
        match_score=payload.match_score,
        liveness_passed=payload.liveness_passed,
        photo_object_key=photo_object_key,
        latitude=payload.latitude,
        longitude=payload.longitude,
        status=status_val,
        flags=flags,
        raw_payload=payload.raw_payload,
    )
    db.add(punch)
    db.flush()
    db.add(AuditLog(
        id=uuid.uuid4(), actor_user_id=None, actor_role=None,
        entity_type='punch', entity_id=str(punch.id), action='punch.create',
        old_value=None,
        new_value={'employee_id': str(punch.employee_id), 'device_id': str(device.id), 'status': punch.status, 'flags': punch.flags},
        request_id=request_id,
    ))
    db.commit()
    db.refresh(punch)
    # B7/D2: synchronous day-build after punch commit.
    import sys as _sys
    import traceback as _tb
    try:
        from app.api.v1.attendance_engine import _tenant_local_today, recompute_day
        _, tz = _tenant_local_today(db)
        local_date = punch.effective_time.astimezone(tz).date()
        print(f"[TRIGGER] emp={punch.employee_id} local_date={local_date}", file=_sys.stderr)
        d1 = recompute_day(db, punch.employee_id, local_date)
        print(f"[TRIGGER] recompute returned: {None if d1 is None else (str(d1.id), str(d1.work_date), d1.status)}", file=_sys.stderr)
        d2 = recompute_day(db, punch.employee_id, local_date - timedelta(days=1))
        print(f"[TRIGGER] prev recompute returned: {None if d2 is None else (str(d2.id), str(d2.work_date), d2.status)}", file=_sys.stderr)
    except Exception as e:
        db.rollback()
        print(f"[TRIGGER FAILED] {type(e).__name__}: {e}", file=_sys.stderr)
        _tb.print_exc(file=_sys.stderr)
    return punch, True


@router.post('', response_model=PunchOut, status_code=status.HTTP_201_CREATED)
def submit_punch(
    payload: PunchIn,
    request: Request,
    db: TenantDbDep,
    tenant: TenantDep,
    device: DeviceDep,
    storage: StorageDep,
    scanner: ScannerDep,
) -> PunchOut:
    server_received_at = datetime.now(timezone.utc)
    request_id = getattr(request.state, 'request_id', None)
    punch, _ = _process_punch(db, device, None, payload, request_id, server_received_at, tenant.crypto, storage, scanner)
    return _to_out(punch)


@router.post('/batch', response_model=PunchBatchOut, status_code=status.HTTP_200_OK)
def submit_punch_batch(
    payload: PunchBatchIn,
    request: Request,
    db: TenantDbDep,
    tenant: TenantDep,
    device: DeviceDep,
    storage: StorageDep,
    scanner: ScannerDep,
) -> PunchBatchOut:
    server_received_at = datetime.now(timezone.utc)
    request_id = getattr(request.state, 'request_id', None)
    accepted = 0
    rejected = 0
    results: list[PunchBatchItemOut] = []
    for i, p in enumerate(payload.punches):
        try:
            punch, _ = _process_punch(db, device, None, p, request_id, server_received_at, tenant.crypto, storage, scanner)
            if punch.status == 'rejected':
                rejected += 1
            else:
                accepted += 1
            results.append(PunchBatchItemOut(index=i, ok=True, punch=_to_out(punch), error=None))
        except AppError as e:
            db.rollback()
            rejected += 1
            results.append(PunchBatchItemOut(index=i, ok=False, punch=None, error={'code': e.code, 'message': e.message, 'details': e.details}))
    return PunchBatchOut(results=results, accepted=accepted, rejected=rejected)


@router.get('/{punch_id}', response_model=PunchOut)
def get_punch(
    punch_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
) -> PunchOut:
    punch = db.get(Punch, punch_id)
    if punch is None:
        raise AppError('record_not_found', 'Punch not found', 404)
    try:
        assert_in_scope(user, punch.employee_id, db)
    except ScopeViolation:
        raise AppError('record_not_found', 'Punch not found', 404) from None
    return _to_out(punch)

# END OF FILE