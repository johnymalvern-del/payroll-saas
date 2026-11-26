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

Photo retention (policy s1): raw facial photographs are no longer stored.
A submitted photo is still decoded, validated and virus-scanned, and is
still required by device.require_photo_for_code -- but the bytes are
discarded once those checks pass, and photo_object_key is always None for
new punches.

GPS retention (policy s5): the raw fix is written to punch_location in the
same transaction as the punch. punch is append-only, so ten_0031 removed
latitude, longitude, gps_accuracy_m and distance_m from it entirely. What
punch keeps is the audit conclusion: geofence_result, geofence_reason and
the coarse distance_band.

Non-biometric fallback (policy s4): method='pin' verifies a 6-digit PIN
against employee.pin_hash before the punch is created. This is the
alternative section 4 requires, and it is deliberately available on *every*
device -- device.allows_code_only governs only method='code', which performs
no verification at all.

A PIN punch is NOT flagged as an exception. The fallback is a mandated right,
not a suspicious event; surfacing it in the exception queue would be exactly
the detriment section 4 forbids. `punch.method` is the record, and HR can
query on it.

PIN verification commits independently of the punch. A failed attempt is a
security event that must survive even though no punch was created, so the
counter increment is committed before the error is raised and before any
punch transaction begins.

list_punches eager-loads the relationship with selectinload -- 100 rows each
needing one lazily-loaded location would be 100 extra queries. Single-punch
reads use the default lazy load. The write path deliberately reads the value
off the object it just created rather than triggering a lazy load, because at
that moment the relationship may not resolve yet.
"""
from __future__ import annotations

import base64
import json
import re
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
from app.core.security import verify_password
from app.db.tenant.models.attendance import Punch, PunchLocation
from app.db.tenant.models.organisation import Site
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.scanner.base import VirusScanner
from app.services.fraud import (
    RAPID_PUNCH_WINDOW_MINUTES,
    TravelVerdict,
    assess_travel,
    is_rapid_succession,
)
from app.services.biometric_verify import (
    BiometricResult,
    BiometricVerdict,
    ProbeInvalid,
    decode_probe_template,
    is_biometric_method,
    verify_biometric_punch,
)
from app.services.geofence import GeofenceVerdict, evaluate_geofence
from app.storage.base import Storage

router = APIRouter(prefix='/punches', tags=['punches'])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_BATCH_BODY_MAX_BYTES = 5 * 1024 * 1024
_PHOTO_MAX_BYTES = 300 * 1024
_RAW_PAYLOAD_MAX_BYTES = 8 * 1024

# Upper bound that fits punch_location.gps_accuracy_m NUMERIC(6,2) without
# overflow. A device reporting beyond this is either broken or lying; we
# keep the punch and record the verdict as inconclusive rather than
# letting a bad number abort the insert.
_ACCURACY_MAX_STORABLE = 9999

# --- Non-biometric fallback (policy s4) ------------------------------------
# 6 digits, not 4: 4 digits is 10,000 combinations, exhaustible in hours at a
# public terminal. argon2 makes each guess expensive, but it places no limit on
# how many guesses can be made -- _PIN_MAX_FAILED_ATTEMPTS does that.
_PIN_RE = re.compile(r'^\d{6}$')
_PIN_MAX_FAILED_ATTEMPTS = 5
_PIN_LOCK_MINUTES = 15


def _verify_employee_pin(db: Any, employee: Employee, pin: str | None) -> None:
    """Verify the fallback PIN, or raise AppError.

    Failures are counted and committed before raising. A failed attempt is a
    security event that must persist even though no punch exists, so the
    counter cannot ride on the punch transaction -- which never starts.

    The order of checks matters:

      1. lockout first, so a locked account cannot be probed for whether the
         PIN is set at all
      2. format, before any hashing: argon2 on a malformed value wastes work
         and tells an attacker nothing useful
      3. verify last, because it is the expensive step

    Returns None on success; the caller proceeds to create the punch.
    """
    if employee.pin_hash is None:
        raise AppError(
            'pin_not_set',
            'No attendance PIN has been set for this employee. '
            'Ask HR to set one.',
            400,
        )

    now = datetime.now(timezone.utc)

    if employee.pin_locked_until is not None and employee.pin_locked_until > now:
        remaining = int((employee.pin_locked_until - now).total_seconds() // 60) + 1
        raise AppError(
            'pin_locked',
            f'Too many incorrect PIN attempts. Try again in {remaining} minute(s), '
            f'or ask HR to unlock the PIN.',
            423,
        )

    if pin is None or not _PIN_RE.match(pin):
        # Deliberately not counted: a client that sent no PIN has not made a
        # guess, and counting it would let a buggy terminal lock out every
        # employee by omitting the field.
        raise AppError(
            'pin_required',
            'This punch requires a 6-digit PIN.',
            400,
        )

    if not verify_password(pin, employee.pin_hash):
        employee.pin_failed_attempts = (employee.pin_failed_attempts or 0) + 1
        if employee.pin_failed_attempts >= _PIN_MAX_FAILED_ATTEMPTS:
            employee.pin_locked_until = now + timedelta(minutes=_PIN_LOCK_MINUTES)
            employee.pin_failed_attempts = 0
            db.commit()
            raise AppError(
                'pin_locked',
                f'Too many incorrect PIN attempts. The PIN is locked for '
                f'{_PIN_LOCK_MINUTES} minutes.',
                423,
            )
        remaining = _PIN_MAX_FAILED_ATTEMPTS - employee.pin_failed_attempts
        db.commit()
        raise AppError(
            'pin_incorrect',
            f'Incorrect PIN. {remaining} attempt(s) remaining before lockout.',
            401,
        )

    # Success clears the lockout state entirely.
    if employee.pin_failed_attempts or employee.pin_locked_until is not None:
        employee.pin_failed_attempts = 0
        employee.pin_locked_until = None
        db.commit()


def _distance_band(distance_m: float | None, radius_m: float | None) -> str:
    """Coarse, permanently-retained descriptor of how far outside a fence.

    'unknown' covers no fix, no site radius, or a verdict that never produced
    a distance. It is also the value every punch captured before ten_0030
    carries, because backfilling would have needed UPDATE on an append-only
    table.

    Band describes geometry; the verdict describes decidability. They can
    disagree by design: 95 m against a 100 m radius is 'within', yet the
    verdict may be INCONCLUSIVE because accuracy was 40 m.
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
    """Display name for a site id, memoised for batch reuse."""
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
        geofence_result=p.geofence_result,
        geofence_reason=p.geofence_reason,
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

    # --- Non-biometric fallback (policy s4) -----------------------------
    # Verified before anything else of substance, and before any punch row
    # exists. A wrong PIN must not produce a punch, an audit row, or a
    # geofence verdict -- it produces an error and a counter increment.
    #
    # No photo is required for a PIN punch: the credential has already
    # verified identity, which is more than method='code' does. If a photo
    # was supplied anyway it is still scanned and discarded below.
    if payload.method == 'pin':
        _verify_employee_pin(
            db,
            employee,
            payload.pin.get_secret_value() if payload.pin is not None else None,
        )

    if payload.method == 'code':
        if not device.allows_code_only:
            raise AppError('code_not_allowed_here', 'This device does not allow code-only punches', 403)
        if device.require_photo_for_code and photo_bytes is None:
            raise AppError('photo_required', 'This device requires a photo for code-only punches', 400)

    effective_time, offset_ms = compute_timing_and_offset(payload.device_time, payload.device_now_at_send, server_received_at)
    flags: list[str] = []

    # --- Biometric verification (privacy policy section 8) ----------
    # The device sends a probe, never a verdict. A client-supplied
    # match_score is ignored for biometric methods: a terminal that
    # reports its own success has not been verified by anything.
    #
    # Anchored after the flags list is created. The block appends to it,
    # so placing it earlier in the function would raise UnboundLocalError
    # at runtime while the patch itself reported success.
    bio_score = None
    bio_liveness = None
    if is_biometric_method(payload.method):
        bio = None
        if payload.probe_template_base64:
            # Malformed base64 cannot arise by accident over a loopback HTTP
            # call, so it means the client built the request wrongly. A defect
            # is worth failing loudly.
            try:
                probe_raw = decode_probe_template(payload.probe_template_base64)
            except ProbeInvalid as exc:
                raise AppError('probe_invalid', str(exc), 400) from None
            bio = verify_biometric_punch(
                db,
                employee_id=payload.employee_id,
                biometric_type=payload.method,
                probe_raw=probe_raw,
                crypto=tenant_crypto,
            )
        else:
            # No probe at all is a reader that could not capture: unplugged,
            # SDK failed, camera blocked. Rejecting the punch would cost the
            # employee a clock-in for a device fault, so the punch is accepted
            # and flagged. Consistent with every other verification outcome in
            # this pipeline, none of which rejects.
            bio = BiometricResult(
                verdict=BiometricVerdict.UNAVAILABLE,
                reason='probe_absent',
                flags=['biometric_verification_unavailable'],
            )
        bio_score = bio.score
        # Liveness is the device's assertion -- there is no server-side way
        # to test it from a template -- so it is recorded as reported and
        # weighed later, not trusted.
        bio_liveness = payload.liveness_passed
        for bio_flag in bio.flags:
            flags.append(bio_flag)

    # Server score wins for biometrics. payload.match_score is only
    # meaningful for methods where nothing verifies anything (code), and
    # for those it is a device claim in any case.
    effective_score = (
        bio_score if is_biometric_method(payload.method) else payload.match_score
    )
    effective_liveness = (
        bio_liveness
        if is_biometric_method(payload.method)
        else payload.liveness_passed
    )
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
    for f in classify_match(effective_score, effective_liveness, 60):
        flags.append(f)
        if status_val == 'accepted':
            status_val = 'low_confidence'

    # --- Phase 2: geofence verdict --------------------------------------
    # The fence tested is the *device's* site, not the employee's. Using
    # the employee's primary site would be circular reasoning: anyone
    # clocking at their own branch would be "inside" by construction.
    raw_accuracy = payload.gps_accuracy_m
    accuracy_val = raw_accuracy
    if accuracy_val is not None and (accuracy_val < 0 or accuracy_val > _ACCURACY_MAX_STORABLE):
        accuracy_val = None
    geofence_result_val = None
    geofence_reason_val = None
    distance_val = None
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

    # --- Slice A: fraud heuristics (flags only, never a rejection) ----
    # Same principle as the geofence verdict: suspicion is recorded and
    # routed to a human, never used to discard a clock-in. A punch
    # quietly rejected because a heuristic fired becomes an unpaid hour,
    # which is a worse outcome than the fraud it was guarding against.
    #
    # Both queries exclude rejected and duplicate punches, matching the
    # attendance computation. A rejected punch is not a reference point
    # for where somebody has been.
    prev = db.execute(
        select(
            Punch.effective_time,
            PunchLocation.latitude,
            PunchLocation.longitude,
        )
        .outerjoin(PunchLocation, PunchLocation.punch_id == Punch.id)
        .where(
            Punch.employee_id == employee.id,
            Punch.effective_time < effective_time,
            Punch.status.notin_(('duplicate', 'rejected')),
        )
        .order_by(Punch.effective_time.desc())
        .limit(1)
    ).first()

    # The outer join is deliberate. Once retention purges
    # punch_location, the punch survives with NULL coordinates here, and
    # assess_travel reports UNAVAILABLE. That must never be read as
    # clean: a check that passes because the evidence was deleted is
    # worse than no check, because it reports 'verified' when it means
    # 'unknown'.
    travel = assess_travel(
        prev_latitude=prev.latitude if prev is not None else None,
        prev_longitude=prev.longitude if prev is not None else None,
        prev_at=prev.effective_time if prev is not None else None,
        latitude=payload.latitude,
        longitude=payload.longitude,
        at=effective_time,
    )
    if travel.verdict is TravelVerdict.IMPOSSIBLE:
        flags.append('impossible_travel')

    recent = db.scalars(
        select(Punch.effective_time).where(
            Punch.employee_id == employee.id,
            Punch.effective_time >= effective_time - timedelta(
                minutes=RAPID_PUNCH_WINDOW_MINUTES
            ),
            Punch.effective_time <= effective_time,
            Punch.status.notin_(('duplicate', 'rejected')),
        )
    ).all()
    if is_rapid_succession(list(recent) + [effective_time]):
        flags.append('rapid_succession')

    # --- Photo: validate, scan, discard ---------------------------------
    # Policy s1 forbids retaining raw facial photographs once processing is
    # complete. The scan still runs -- an unchecked upload is a security
    # problem regardless of whether we keep it -- but the bytes are dropped.
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
        geofence_result=geofence_result_val,
        geofence_reason=geofence_reason_val,
        distance_band=_distance_band(distance_val, radius_val),
        status=status_val,
        flags=flags,
        raw_payload=payload.raw_payload,
    )
    db.add(punch)
    db.flush()

    # --- Policy s5: the raw fix goes to its own table --------------------
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
        new_value={'employee_id': str(punch.employee_id), 'device_id': str(device.id), 'status': punch.status, 'flags': punch.flags, 'method': punch.method},
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