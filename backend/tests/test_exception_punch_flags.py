"""Punch-flag to exception mapping tests (Phase 4).

Before Phase 4, _expected_exception_types derived exceptions from five
sources only: two day flags, two day statuses, pending overtime, and
Punch.status == "low_confidence". Every other punch flag was written and
read by nothing -- including "device_clock_gap", which existed in the
vocabulary of both exceptions.py and demo_seed.py but was never emitted.

These tests pin the mapping:

    clock_gap             -> device_clock_gap
    future_time           -> device_clock_ahead
    liveness_failed       -> liveness_failed
    geofence_outside      -> geofence_outside
    geofence_inconclusive -> geofence_inconclusive

future_time was mapped late, and only after the attendance computation was
corrected to exclude rejected punches. Before that correction the mapping
would have been misleading: the punch was paid *and* flagged, so the
exception asked HR to review a device clock while the money had already
gone out. Now the two halves agree -- the punch is excluded from pay and
the device fault is visible.

That split is worth understanding before changing either side: the punch
SELECT in recompute_day filters on status, while the flag SELECT in
_expected_exception_types does not. A rejected punch is therefore invisible
to minutes and visible to the queue, which is exactly the intended
behaviour and is asserted in test_future_time_flag_creates_exception.

The negative-control test here is the important guard: a flag that is NOT
in the mapping must remain inert. Without it, a future change could map
every flag indiscriminately and flood the exception queue.

Note on liveness: a punch that fails liveness carries status
"low_confidence" (set by _process_punch for either low match score or
failed liveness) AND the "liveness_failed" flag. Such a punch therefore
raises two exceptions. That is deliberate -- they are different findings
about the same punch -- and it is asserted explicitly so the behaviour
cannot change silently.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.attendance_engine import recompute_day
from app.core.security import hash_password
from app.db.tenant.models.attendance import (
    CountryCalendar,
    ExceptionItem,
    Punch,
    Shift,
    ShiftRateRule,
)
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine

SA = ZoneInfo("Africa/Johannesburg")

WORK_DATE = date(2024, 5, 1)


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

    slug = f"pflag-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="PunchFlag Test",
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
        s.close()


# ---------------------------------------------------------------------------
# Helpers, matching the style of test_exception_auto.py
# ---------------------------------------------------------------------------


def _mk_emp(session, code, *, dflt_shift=None):
    employee = Employee(
        employee_code=code,
        first_name="A",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        default_shift_id=dflt_shift,
        row_version=1,
    )
    session.add(employee)
    session.commit()
    return employee


def _mk_shift(session):
    shift = Shift(
        name=f"S-{uuid.uuid4().hex[:6]}",
        start_time=time(8, 0),
        length_minutes=480,
        unpaid_break_minutes=60,
        paid_break_minutes=0,
        grace_late_minutes=0,
        grace_early_minutes=0,
        grace_mode="threshold",
        rounding_minutes=0,
        rounding_mode="nearest",
        min_overtime_minutes=0,
        overtime_requires_approval=True,
        max_shift_minutes=720,
        match_tolerance_minutes=60,
        salaried_premium_mode="full",
        pay_early_arrival=False,
        is_active=True,
        row_version=1,
    )
    session.add(shift)
    session.commit()
    return shift


def _mk_rule(session, shift_id):
    rule = ShiftRateRule(
        shift_id=shift_id,
        day_type="weekday",
        kind="normal",
        tier=1,
        tier_up_to_minutes=None,
        method="multiplier",
        value=Decimal("1.0"),
        flat_unit=None,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )
    session.add(rule)
    session.commit()
    return rule


def _mk_cal(session, year):
    session.add(
        CountryCalendar(
            country_code="ZA",
            holiday_date=date(year, 12, 25),
            name="Xmas",
            source_ref="test",
        )
    )
    session.commit()


def _mk_punch(session, employee_id, ts_utc, *, status="accepted", flags=None):
    punch = Punch(
        client_punch_id=uuid.uuid4(),
        payload_hash="0" * 64,
        employee_id=employee_id,
        device_time=ts_utc,
        effective_time=ts_utc,
        offset_ms=0,
        method="fingerprint",
        status=status,
        flags=list(flags or []),
        raw_payload={},
    )
    session.add(punch)
    session.commit()
    return punch


def _sa_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=SA).astimezone(timezone.utc)


def _open_exception(db, employee_id, work_date, exc_type):
    return db.scalar(
        select(ExceptionItem).where(
            ExceptionItem.employee_id == employee_id,
            ExceptionItem.work_date == work_date,
            ExceptionItem.type == exc_type,
            ExceptionItem.status == "open",
        )
    )


def _open_exception_types(db, employee_id, work_date):
    return set(
        db.scalars(
            select(ExceptionItem.type).where(
                ExceptionItem.employee_id == employee_id,
                ExceptionItem.work_date == work_date,
                ExceptionItem.status == "open",
            )
        ).all()
    )


def _worked_day_setup(db, code="P1"):
    """Employee on a real shift, clocked in at 08:00 local.

    A shift is configured so the day lands on a genuine worked status
    rather than "absent" -- otherwise every test would also pick up
    absent_expected from the status mapping and the assertions would be
    muddied.
    """
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    employee = _mk_emp(db, code, dflt_shift=shift.id)
    return employee


# ---------------------------------------------------------------------------
# The five mappings
# ---------------------------------------------------------------------------


def test_clock_gap_flag_creates_device_clock_gap_exception(db):
    employee = _worked_day_setup(db, "CG1")
    _mk_punch(db, employee.id, _sa_utc(2024, 5, 1, 8, 0), flags=["clock_gap"])
    recompute_day(db, employee.id, WORK_DATE)
    db.expire_all()

    exc = _open_exception(db, employee.id, WORK_DATE, "device_clock_gap")
    assert exc is not None, "clock_gap flag did not raise device_clock_gap"
    assert exc.suggested_fix.get("action") == "review_device_clock"


def test_future_time_flag_creates_exception(db):
    """A device clock running fast must be visible, even though it is unpaid.

    The punch is status="rejected", exactly as _process_punch writes it. That
    status now excludes the punch from the minutes computation (engine.py:808),
    so a lone rejected punch leaves the day with no sessions and no pay. The
    flag query in _expected_exception_types does not filter on status, so the
    device fault still reaches the HR queue.

    Both halves are asserted deliberately. A fix that excluded the punch from
    pay but also hid it from HR would turn a device fault into an unexplained
    absence -- and an absence can become a deduction.
    """
    employee = _worked_day_setup(db, "FT1")
    _mk_punch(
        db, employee.id, _sa_utc(2024, 5, 1, 8, 0),
        status="rejected", flags=["future_time"],
    )
    day = recompute_day(db, employee.id, WORK_DATE)
    db.expire_all()

    # Not paid: a rejected punch forms no session.
    assert day is not None
    assert day.status != "worked"
    assert day.worked_minutes == 0

    # Still visible: the flag survives the status filter.
    exc = _open_exception(db, employee.id, WORK_DATE, "device_clock_ahead")
    assert exc is not None, "future_time flag did not raise device_clock_ahead"
    assert exc.suggested_fix.get("action") == "review_device_clock"


def test_liveness_failed_flag_creates_its_own_exception(db):
    employee = _worked_day_setup(db, "LV1")
    _mk_punch(
        db, employee.id, _sa_utc(2024, 5, 1, 8, 0),
        status="low_confidence", flags=["liveness_failed"],
    )
    recompute_day(db, employee.id, WORK_DATE)
    db.expire_all()

    exc = _open_exception(db, employee.id, WORK_DATE, "liveness_failed")
    assert exc is not None, "liveness_failed flag did not raise its own exception"
    assert exc.suggested_fix.get("action") == "reject_punch"


def test_liveness_failure_raises_both_low_confidence_and_liveness(db):
    """Documents the deliberate doubled queue.

    _process_punch sets status="low_confidence" for either a low match
    score or a failed liveness check, so a liveness failure also matches
    the status-based low_confidence query. Two exceptions result. If this
    becomes operationally noisy, remove the liveness_failed entry from
    _EXCEPTION_TYPES_FROM_PUNCH_FLAGS and this test will fail loudly --
    which is the point.
    """
    employee = _worked_day_setup(db, "LV2")
    _mk_punch(
        db, employee.id, _sa_utc(2024, 5, 1, 8, 0),
        status="low_confidence", flags=["liveness_failed"],
    )
    recompute_day(db, employee.id, WORK_DATE)
    db.expire_all()

    types = _open_exception_types(db, employee.id, WORK_DATE)
    assert "low_confidence" in types
    assert "liveness_failed" in types


def test_geofence_outside_flag_creates_exception(db):
    employee = _worked_day_setup(db, "GO1")
    _mk_punch(db, employee.id, _sa_utc(2024, 5, 1, 8, 0), flags=["geofence_outside"])
    recompute_day(db, employee.id, WORK_DATE)
    db.expire_all()

    exc = _open_exception(db, employee.id, WORK_DATE, "geofence_outside")
    assert exc is not None, "geofence_outside flag did not raise an exception"
    assert exc.suggested_fix.get("action") == "review_location"


def test_geofence_inconclusive_flag_creates_exception(db):
    employee = _worked_day_setup(db, "GI1")
    _mk_punch(db, employee.id, _sa_utc(2024, 5, 1, 8, 0), flags=["geofence_inconclusive"])
    recompute_day(db, employee.id, WORK_DATE)
    db.expire_all()

    exc = _open_exception(db, employee.id, WORK_DATE, "geofence_inconclusive")
    assert exc is not None, "geofence_inconclusive flag did not raise an exception"
    assert exc.suggested_fix.get("action") == "review_location"


# ---------------------------------------------------------------------------
# Negative control
# ---------------------------------------------------------------------------


def test_unmapped_flag_raises_nothing(db):
    """A flag absent from the mapping must stay inert.

    employee_not_active is written by _process_punch but is not in
    _EXCEPTION_TYPES_FROM_PUNCH_FLAGS. If a future change maps every flag
    indiscriminately, this test fails.

    mapped_types is enumerated by hand rather than derived from the mapping
    dict, so that adding a mapping without deciding whether it belongs here
    shows up as a stale test rather than silently widening the guard.
    """
    employee = _worked_day_setup(db, "NM1")
    _mk_punch(db, employee.id, _sa_utc(2024, 5, 1, 8, 0), flags=["employee_not_active"])
    recompute_day(db, employee.id, WORK_DATE)
    db.expire_all()

    types = _open_exception_types(db, employee.id, WORK_DATE)
    mapped_types = {
        "device_clock_gap",
        "device_clock_ahead",
        "liveness_failed",
        "geofence_outside",
        "geofence_inconclusive",
    }
    assert not (types & mapped_types), (
        f"unmapped flag produced exceptions: {sorted(types & mapped_types)}"
    )


def test_flags_outside_the_day_window_are_ignored(db):
    """The punch lookup is bounded, not company-wide.

    A flagged punch three weeks away must not attach to this work_date.
    """
    employee = _worked_day_setup(db, "WIN1")
    _mk_punch(db, employee.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(
        db, employee.id, _sa_utc(2024, 5, 22, 8, 0), flags=["geofence_outside"],
    )
    recompute_day(db, employee.id, WORK_DATE)
    db.expire_all()

    assert _open_exception(db, employee.id, WORK_DATE, "geofence_outside") is None

# END OF FILE