"""Punch endpoints (Chapter 2A).

Phase 2 (biometric attendance programme): punches are now evaluated
against the geofence of the site their *device* is registered to, and the
verdict is persisted on the punch row.

The verdict never changes the punch status. An out-of-fence or
inconclusive punch is still accepted, flagged, and left for HR to
resolve. Rejecting it here would discard the employee's clock-in, and a
missing clock-in is a worse outcome than an exception somebody can look
at -- that is also the safeguard that stops a GPS or biometric problem
from silently becoming an unpaid deduction downstream.

Phase 5: PunchOut carries site_name so the clock-in screen can confirm the
branch by name. The lookup is cached per request because a batch shares a
single device and therefore a single site.

Photo retention (policy s1): raw facial photographs are no longer stored.
A submitted photo is still decoded, validated and virus-scanned, and is
still required by device.require_photo_for_code -- but the bytes are
discarded once those checks pass, and photo_object_key is always None for
new punches. Existing stored photographs and their keys are untouched;
removing those needs the dependency investigation required by policy s1
and is deliberately not attempted here.

GPS retention (policy s5, ten_0030): the raw fix is written to
punch_location in the same transaction as the punch, because punch itself
is append-only and a mutable column cannot live there. The punch keeps a
coarse distance_band permanently; the exact distance and accuracy are
deleted with the coordinates when retention expires.

The location row is written whenever a fix exists, even when no verdict
could be reached. A site with no geofence radius produces no distance, but
the employee's position was still captured, and retention policy applies to
it on the same 30-day schedule as any other. Gating the write on having a
distance would mean ten_0031 destroyed those coordinates abruptly at the
column drop instead of expiring them on schedule.

PunchOut.location is the transitional read shape: the fix is exposed as a
nested object while the flat latitude/longitude/gps_accuracy_m/distance_m
fields still mirror punch. After ten_0031 those columns are gone, the flat
fields become permanently None, and location is the only place to read a
fix from. Clients should prefer location already.

list_punches eager-loads the relationship with selectinload -- 100 rows each
needing one lazily-loaded location would be 100 extra queries. Single-punch
reads use the default lazy load, one query each, which is correct there. The
write path deliberately reads the value off the payload rather than the
relationship: the row is in the session and unflushed to the relationship,
so a lazy load at that moment could legitimately miss it.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

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
    PunchLocationOut,
    PunchOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.attendance import Punch, PunchLocation
from app.db.tenant.models.organisation import Site
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.scanner.base import VirusScanner
from app.services.geofence import GeofenceVerdict, evaluate_geofence
from app.storage.base import Storage

router = APIRouter(prefix='/punches', tags=['punches'])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_BATCH_BODY_MAX_BYTES = 5 * 1024 * 1024
_PHOTO_MAX_BYTES = 300 * 1024
_RAW_PAYLOAD_MAX_BYTES = 8 * 1024

# Upper bound that fits punch.gps_accuracy_m NUMERIC(6,2) without
# overflow. A device reporting beyond this is either broken or lying; we
# keep the punch and record the verdict as inconclusive rather than
# letting a bad number abort the insert.
_ACCURACY_MAX_STORABLE = 9999


def _distance_band(distance_m: float | None, radius_m: float | None) -> str:
    """Coarse, permanently-retained descriptor of how far outside a fence.

    Privacy policy section 5: the exact distance is purged with the
    coordinates, so what survives must be enough to defend the verdict
    without localising the employee. "near" vs "distant" preserves the
    distinction an auditor needs; neither pins a position.

    'unknown' covers three cases -- no fix, no site radius, or a verdict
    that never produced a distance. It is also the value every punch
    captured before ten_0030 carries, because backfilling them would
    require UPDATE on an append-only table.

    Note the band describes geometry while the verdict describes
    decidability, so they can disagree by design: distance 95 m against a
    100 m radius is 'within', yet the verdict may be INCONCLUSIVE because
    the accuracy was 40 m. Neither is wrong.
    """
    if distance_m is None or radius_m is None or radius_m <= 0:
        return 'unknown'
    if distance_m <= radius_m:
        return 'within'
    if distance_m <= 2.0 * radius_m:
        return 'near'
    return 'distant'


def _location_out(loc: PunchLocation | None) -> PunchLocationOut | None:
    if loc is None:
        return None
    return PunchLocationOut(
        latitude=loc.latitude,
        longitude=loc.longitude,
        gps_accuracy_m=loc.gps_accuracy_m,
        distance_m=loc.distance_m,
        captured_at=loc.captured_at,
    )


def _site_name(db: Any, site_id: uuid.UUID | None, cache: dict | None = None) -> str | None:
    """Display name for a site id, memoised for batch reuse.

    A batch of 500 punches from one device shares one site, so without a
    cache this would be 500 identical db.get() calls. The identity map
    would make them cheap but not free.
    """
    if site_id is None:
        return None
    if cache is not None and site_id in cache:
        return cache[site_id]
    site = db.get(Site, site_id)
    name = site.name if site is not None else None
    if cache is not None:
        cache[site_id] = name
    return name


def _to_out(
    p: Punch,
    *,
    site_name: str | None = None,
    location: PunchLocation | None = None,
) -> PunchOut:
    return PunchOut(
        id=p.id, client_punch_id=p.client_punch_id, employee_id=p.employee_id,
        device_id=p.device_id, site_id=p.site_id, site_name=site_name,
        server_received_at=p.server_received_at, device_time=p.device_time,
        device_now_at_send=p.device_now_at_send, effective_time=p.effective_time,
        offset_ms=p.offset_ms, method=p.method, match_score=p.match_score,
        liveness_passed=p.liveness_passed, photo_object_key=p.photo_object_key,
        latitude=p.latitude, longitude=p.longitude,
        gps_accuracy_m=p.gps_accuracy_m,
        geofence_result=p.geofence_result,
        geofence_reason=p.geofence_reason,
        distance_m=p.distance_m,
        distance_band=p.distance_band,
        location=_location_out(location),
        status=p.status,
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
    # One extra query for the whole page rather than one per punch.
    q = q.options(selectinload(Punch.location))
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
    name_cache: dict = {}
    return PunchListOut(
        items=[
            _to_out(
                r,
                site_name=_site_name(db, r.site_id, name_cache),
                location=r.location,
            )
            for r in rows
        ],
        next_cursor=next_cursor,
        total=total,
    )


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
) -> tuple[Punch, list[str]]:
    existing = _handle_idempotent(db, device.id, payload)
    if existing is not None:
        return existing, []
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

    # --- Phase 2: geofence verdict --------------------------------------
    # The fence tested is the *device's* site, not the employee's. Using
    # the employee's primary site would be circular reasoning: anyone
    # clocking at their own branch would be "inside" by construction, and
    # an employee clocking from home would be judged against a fence they
    # were never near anyway.
    raw_accuracy = payload.gps_accuracy_m
    accuracy_val = raw_accuracy
    if accuracy_val is not None and (accuracy_val < 0 or accuracy_val > _ACCURACY_MAX_STORABLE):
        # Unstorable or implausible: keep it out of the column (NUMERIC(6,2)
        # would raise), but still hand the raw value to the evaluator so the
        # reason tag records that the device reported nonsense.
        accuracy_val = None
    geofence_result_val = None
    geofence_reason_val = None
    distance_val = None
    # Hoisted out of the site branch so the band can be computed whether or
    # not a verdict was reached.
    radius_val: float | None = None
    if device.site_id is None:
        geofence_result_val = GeofenceVerdict.UNAVAILABLE.value
        geofence_reason_val = 'device_site_not_specified'
    else:
        site = db.get(Site, device.site_id)
        if site is None:
            geofence_result_val = GeofenceVerdict.UNAVAILABLE.value
            geofence_reason_val = 'site_record_missing'
        else:
            radius_val = None if site.geofence_radius_m is None else float(site.geofence_radius_m)
            geo = evaluate_geofence(
                latitude=payload.latitude,
                longitude=payload.longitude,
                accuracy_m=raw_accuracy,
                site_latitude=site.latitude,
                site_longitude=site.longitude,
                geofence_radius_m=site.geofence_radius_m,
            )
            geofence_result_val = geo.verdict.value
            geofence_reason_val = geo.reason
            distance_val = None if geo.distance_m is None else round(geo.distance_m, 2)

    # A location verdict never flips status. See the module docstring.
    if geofence_result_val == GeofenceVerdict.OUTSIDE.value:
        flags.append('geofence_outside')
    elif geofence_result_val == GeofenceVerdict.INCONCLUSIVE.value:
        flags.append('geofence_inconclusive')

    # --- Photo: validate, scan, discard ---------------------------------
    # Policy s1 forbids retaining raw facial photographs once processing is
    # complete. The scan still runs -- an unchecked upload is a security
    # problem regardless of whether we keep it -- but the bytes are dropped
    # and photo_object_key is left None.
    photo_object_key = None
    if photo_bytes is not None:
        scan_result = scanner.scan(photo_bytes)
        if not scan_result.clean:
            raise AppError('photo_scan_failed', 'Photo failed virus scan', 400)

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
        gps_accuracy_m=accuracy_val,
        geofence_result=geofence_result_val,
        geofence_reason=geofence_reason_val,
        distance_m=distance_val,
        distance_band=_distance_band(distance_val, radius_val),
        status=status_val,
        flags=flags,
        raw_payload=payload.raw_payload,
    )
    db.add(punch)
    db.flush()

    # --- Policy s5: the raw fix goes to its own table --------------------
    # Written in the same transaction as the punch, so a punch can never
    # exist with a half-recorded location. punch itself stays append-only;
    # this row is the part retention is allowed to delete.
    #
    # Gated on the *fix* existing, not on a distance being computable. A
    # site with no radius yields no distance, but the position was still
    # captured and must expire on the normal schedule rather than vanish
    # when ten_0031 drops the columns from punch.
    location_row: PunchLocation | None = None
    if payload.latitude is not None and payload.longitude is not None:
        location_row = PunchLocation(
            punch_id=punch.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            gps_accuracy_m=accuracy_val,
            distance_m=distance_val,
            captured_at=punch.effective_time,
        )
        db.add(location_row)

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
    warnings: list[str] = []
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
        warnings = ["attendance_recompute_failed"]
        print(f"[TRIGGER FAILED] {type(e).__name__}: {e}", file=_sys.stderr)
        _tb.print_exc(file=_sys.stderr)
    punch.__dict__['_si_location'] = location_row
    return punch, warnings


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
    punch, warnings = _process_punch(db, device, None, payload, request_id, server_received_at, tenant.crypto, storage, scanner)
    out = _to_out(
        punch,
        site_name=_site_name(db, punch.site_id),
        location=punch.__dict__.get('_si_location'),
    )
    out.warnings = warnings
    return out


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
    name_cache: dict = {}
    for i, p in enumerate(payload.punches):
        try:
            punch, warnings = _process_punch(db, device, None, p, request_id, server_received_at, tenant.crypto, storage, scanner)
            if punch.status == 'rejected':
                rejected += 1
            else:
                accepted += 1
            item_out = _to_out(
                punch,
                site_name=_site_name(db, punch.site_id, name_cache),
                location=punch.__dict__.get('_si_location'),
            )
            item_out.warnings = warnings
            results.append(PunchBatchItemOut(index=i, ok=True, punch=item_out, error=None))
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
    return _to_out(punch, site_name=_site_name(db, punch.site_id), location=punch.location)

# END OF FILE