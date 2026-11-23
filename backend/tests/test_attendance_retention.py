"""Coordinate retention tests (privacy policy section 5).

The properties that matter here are not "does it delete rows" but:

  * the punch and its verdict survive the purge, because the attendance
    record depends on them
  * evidence is never destroyed for a day under an open exception
  * a locked payroll day does NOT hold, per the agreed policy
  * dry_run touches nothing and is the default
  * a second sweep is a no-op

ten_0031 dropped latitude, longitude, gps_accuracy_m and distance_m from
punch entirely, so there is nothing left on the punch to update. The purge is
a DELETE from punch_location and only a DELETE: punch is append-only, UPDATE
is revoked and a trigger raises. An earlier version of this file asserted
that latitude/longitude on punch became NULL after a sweep; that design was
impossible and the tests were replaced rather than adjusted.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.tenant.models.attendance import AttendanceDay, ExceptionItem, Punch, PunchLocation
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.db.tenant.session import get_tenant_engine
from app.services.attendance_retention import (
    count_expired_with_coordinates,
    purge_expired_coordinates,
)

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=45)
FRESH = NOW - timedelta(days=2)

CT_LAT = Decimal("-33.924900")
CT_LON = Decimal("18.424100")


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    from app.services.provisioning import (
        _drop_tenant_database,
        _tenant_db_name,
        provision_tenant,
    )

    slug = f"retn-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Retention Test Co",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(
            slug=result.slug,
            tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
    finally:
        try:
            _drop_tenant_database(db_name)
        except Exception:
            pass
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


@pytest.fixture()
def db(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _mk_emp(session, code):
    employee = Employee(
        employee_code=code,
        first_name="A",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    session.add(employee)
    session.commit()
    return employee


def _mk_punch(session, employee_id, ts, *, with_location=True):
    """A punch plus, optionally, its punch_location row.

    Mirrors what _process_punch writes after ten_0031: the verdict lives on
    the punch, the raw fix lives in its own table, and nothing that must
    expire is on the punch.
    """
    punch = Punch(
        client_punch_id=uuid.uuid4(),
        payload_hash="0" * 64,
        employee_id=employee_id,
        device_time=ts,
        effective_time=ts,
        offset_ms=0,
        method="fingerprint",
        status="accepted",
        flags=["geofence_outside"],
        raw_payload={},
        geofence_result="outside" if with_location else None,
        geofence_reason="outside_geofence" if with_location else None,
        distance_band="distant" if with_location else "unknown",
    )
    session.add(punch)
    session.flush()
    loc = None
    if with_location:
        loc = PunchLocation(
            punch_id=punch.id,
            latitude=CT_LAT,
            longitude=CT_LON,
            gps_accuracy_m=Decimal("8.00"),
            distance_m=Decimal("19152.30"),
            captured_at=ts,
        )
        session.add(loc)
    session.commit()
    return punch, loc


def _mk_open_exception(session, employee_id, work_date, *, exc_type="geofence_outside"):
    session.add(
        ExceptionItem(
            employee_id=employee_id,
            work_date=work_date,
            type=exc_type,
            source_ref={},
            suggested_fix={},
            status="open",
        )
    )
    session.commit()


def _mk_locked_day(session, employee_id, work_date):
    session.add(
        AttendanceDay(
            employee_id=employee_id,
            work_date=work_date,
            status="worked",
            worked_minutes=480,
            normal_minutes=480,
            overtime_minutes=0,
            raw_minutes=480,
            locked=True,
        )
    )
    session.commit()


def _locations_for(session, punch_id):
    return list(
        session.scalars(
            select(PunchLocation).where(PunchLocation.punch_id == punch_id)
        ).all()
    )


def _purge_and_commit(db, **kwargs):
    result = purge_expired_coordinates(db, now=NOW, **kwargs)
    db.commit()
    return result


# ---------------------------------------------------------------------------
# The purge itself
# ---------------------------------------------------------------------------


def test_purges_expired_location_but_keeps_punch_and_verdict(db):
    emp = _mk_emp(db, "R1")
    punch, _loc = _mk_punch(db, emp.id, OLD)

    result = _purge_and_commit(db, retention_days=30, dry_run=False)

    assert result.candidates == 1
    assert result.purged == 1
    assert result.skipped_held == 0

    db.expire_all()
    assert _locations_for(db, punch.id) == []

    # The punch record and its audit conclusion survive untouched.
    row = db.get(Punch, punch.id)
    assert row is not None
    assert row.geofence_result == "outside"
    assert row.geofence_reason == "outside_geofence"
    assert row.distance_band == "distant"
    assert row.status == "accepted"


def test_leaves_recent_locations_alone(db):
    emp = _mk_emp(db, "R2")
    punch, _loc = _mk_punch(db, emp.id, FRESH)

    result = _purge_and_commit(db, retention_days=30, dry_run=False)

    assert result.candidates == 0
    assert result.purged == 0
    db.expire_all()
    assert len(_locations_for(db, punch.id)) == 1


def test_punch_without_location_is_not_a_candidate(db):
    emp = _mk_emp(db, "R3")
    _mk_punch(db, emp.id, OLD, with_location=False)

    result = _purge_and_commit(db, retention_days=30, dry_run=False)

    assert result.candidates == 0
    assert result.purged == 0


# ---------------------------------------------------------------------------
# Holds
# ---------------------------------------------------------------------------


def test_open_exception_holds_regardless_of_age(db):
    """An open exception about an OLD punch must hold it.

    This is the defect the earlier implementation had: it date-windowed the
    hold query, so an exception about a 45-day-old punch fell outside the
    window and the coordinates were deleted -- exactly the case where
    deletion is least safe.
    """
    emp = _mk_emp(db, "R4")
    punch, _loc = _mk_punch(db, emp.id, OLD)
    _mk_open_exception(db, emp.id, OLD.date())

    result = _purge_and_commit(db, retention_days=30, dry_run=False)

    assert result.skipped_held == 1
    assert result.purged == 0
    db.expire_all()
    assert len(_locations_for(db, punch.id)) == 1, "held coordinates must survive"


def test_locked_day_does_not_hold(db):
    """A finalised payroll period must NOT retain coordinates forever.

    The verdict on the punch already answers the payroll-audit question a
    locked period raises; the raw position adds nothing and would be kept
    indefinitely, since locked days stay locked.
    """
    emp = _mk_emp(db, "R5")
    punch, _loc = _mk_punch(db, emp.id, OLD)
    _mk_locked_day(db, emp.id, OLD.date())

    result = _purge_and_commit(db, retention_days=30, dry_run=False)

    assert result.skipped_held == 0
    assert result.purged == 1
    db.expire_all()
    assert _locations_for(db, punch.id) == []


def test_purges_unheld_while_skipping_held(db):
    held = _mk_emp(db, "R6-HELD")
    free = _mk_emp(db, "R6-FREE")
    held_punch, _ = _mk_punch(db, held.id, OLD)
    free_punch, _ = _mk_punch(db, free.id, OLD)
    _mk_open_exception(db, held.id, OLD.date())

    result = _purge_and_commit(db, retention_days=30, dry_run=False)

    assert result.candidates == 2
    assert result.purged == 1
    assert result.skipped_held == 1
    db.expire_all()
    assert len(_locations_for(db, held_punch.id)) == 1
    assert _locations_for(db, free_punch.id) == []


def test_resolving_exception_releases_the_hold(db):
    """Holds are derived from status, so nothing has to be unset manually."""
    emp = _mk_emp(db, "R7")
    punch, _loc = _mk_punch(db, emp.id, OLD)
    _mk_open_exception(db, emp.id, OLD.date())

    first = _purge_and_commit(db, retention_days=30, dry_run=False)
    assert first.skipped_held == 1
    assert first.purged == 0

    exc = db.scalar(
        select(ExceptionItem).where(
            ExceptionItem.employee_id == emp.id,
            ExceptionItem.status == "open",
        )
    )
    exc.status = "resolved"
    db.commit()

    second = _purge_and_commit(db, retention_days=30, dry_run=False)
    assert second.skipped_held == 0
    assert second.purged == 1
    db.expire_all()
    assert _locations_for(db, punch.id) == []


# ---------------------------------------------------------------------------
# Dry run and idempotency
# ---------------------------------------------------------------------------


def test_dry_run_changes_nothing_and_writes_no_audit(db):
    emp = _mk_emp(db, "R8")
    punch, _loc = _mk_punch(db, emp.id, OLD)

    result = _purge_and_commit(db, retention_days=30, dry_run=True)

    assert result.dry_run is True
    assert result.purged == 1, "a dry run still reports what it would do"
    db.expire_all()
    assert len(_locations_for(db, punch.id)) == 1
    audit_count = db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "attendance.coordinates.purged")
    )
    assert audit_count == 0


def test_dry_run_is_the_default(db):
    """Deleting personal data must be an explicit act."""
    emp = _mk_emp(db, "R9")
    punch, _loc = _mk_punch(db, emp.id, OLD)

    purge_expired_coordinates(db, now=NOW, retention_days=30)
    db.commit()

    db.expire_all()
    assert len(_locations_for(db, punch.id)) == 1


def test_second_sweep_is_a_no_op(db):
    emp = _mk_emp(db, "R10")
    _mk_punch(db, emp.id, OLD)

    first = _purge_and_commit(db, retention_days=30, dry_run=False)
    second = _purge_and_commit(db, retention_days=30, dry_run=False)

    assert first.purged == 1
    assert second.candidates == 0
    assert second.purged == 0


def test_max_batches_bounds_one_run(db):
    emp = _mk_emp(db, "R11")
    for i in range(5):
        _mk_punch(db, emp.id, OLD - timedelta(minutes=i))

    result = _purge_and_commit(
        db, retention_days=30, dry_run=False, batch_size=2, max_batches=1
    )

    # One batch of two rows, remainder left for the next run.
    assert result.purged == 2
    assert result.candidates == 5
    db.expire_all()
    assert count_expired_with_coordinates(db, now=NOW, retention_days=30) == 3


# ---------------------------------------------------------------------------
# Audit and validation
# ---------------------------------------------------------------------------


def test_audit_row_describes_sweep_without_coordinates(db):
    emp = _mk_emp(db, "R12")
    _mk_punch(db, emp.id, OLD)

    _purge_and_commit(db, retention_days=30, dry_run=False)

    rows = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.action == "attendance.coordinates.purged"
            )
        ).all()
    )
    assert len(rows) == 1
    payload = rows[0].new_value
    assert payload["purged"] == 1
    assert payload["retention_days"] == 30
    assert payload["purged_fields"] == [
        "latitude", "longitude", "gps_accuracy_m", "distance_m",
    ]
    assert "geofence_result" in payload["retained_fields"]

    # The audit trail must not itself become a copy of the coordinates.
    serialized = str(payload)
    assert str(CT_LAT) not in serialized
    assert str(CT_LON) not in serialized


def test_negative_retention_rejected(db):
    with pytest.raises(ValueError):
        purge_expired_coordinates(db, now=NOW, retention_days=-1)


def test_non_positive_batch_size_rejected(db):
    with pytest.raises(ValueError):
        purge_expired_coordinates(db, now=NOW, batch_size=0)

# END OF FILE