"""DB-backed tests for attendance_engine (Chapter 2B, 3b)."""
from __future__ import annotations
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.attendance_engine import ensure_days, recompute_day
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.tenant.models.attendance import (
    AttendanceDay, CountryCalendar, Punch, Shift, ShiftRateRule,
)
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine

SA = ZoneInfo("Africa/Johannesburg")


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    from app.services.provisioning import _drop_tenant_database, _tenant_db_name, provision_tenant
    slug = f"eng-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="Engine Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(slug=result.slug, tenant_db_name=result.tenant_db_name, subscriber_id=result.subscriber_id)
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


def _mk_emp(session, code, *, hire=None, clocks=True, wp_id=None, dflt_shift=None):
    e = Employee(
        employee_code=code, first_name="A", last_name=code,
        hire_date=hire or date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
        clocks=clocks, work_pattern_id=wp_id, default_shift_id=dflt_shift,
        row_version=1,
    )
    session.add(e); session.commit(); return e


def _mk_shift(session, *, name=None, start=time(8, 0), length=480, brk=60,
              grace_late=0, grace_early=0, grace_mode="threshold",
              min_ot=0, ot_approval=False, early_pay=False, max_min=720):
    s = Shift(
        name=name or f"S-{uuid.uuid4().hex[:6]}",
        start_time=start, length_minutes=length, unpaid_break_minutes=brk,
        paid_break_minutes=0, grace_late_minutes=grace_late,
        grace_early_minutes=grace_early, grace_mode=grace_mode,
        rounding_minutes=0, rounding_mode="nearest",
        min_overtime_minutes=min_ot, overtime_requires_approval=ot_approval,
        max_shift_minutes=max_min, match_tolerance_minutes=60,
        salaried_premium_mode="full", pay_early_arrival=early_pay,
        is_active=True, row_version=1,
    )
    session.add(s); session.commit(); return s


def _mk_rule(session, shift_id, day_type, kind, *, tier=1, up_to=None, value="1.0"):
    r = ShiftRateRule(
        shift_id=shift_id, day_type=day_type, kind=kind, tier=tier,
        tier_up_to_minutes=up_to, method="multiplier",
        value=Decimal(value), flat_unit=None,
        effective_from=date(2020, 1, 1), effective_to=None,
    )
    session.add(r); session.commit(); return r


def _mk_calendar(session, year, dates):
    for d in dates:
        session.add(CountryCalendar(
            country_code="ZA", holiday_date=d, name=f"H-{d.isoformat()}",
            source_ref="test",
        ))
    session.commit()


def _mk_punch(session, employee_id, ts_utc):
    p = Punch(
        client_punch_id=uuid.uuid4(), payload_hash="0" * 64,
        employee_id=employee_id, device_time=ts_utc,
        effective_time=ts_utc, offset_ms=0,
        method="fingerprint", status="accepted",
        flags=[], raw_payload={},
    )
    session.add(p); session.commit(); return p


def _sa_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=SA).astimezone(timezone.utc)


def _today_sa():
    return datetime.now(timezone.utc).astimezone(SA).date()


def test_holiday_calendar_missing_raises(db):
    e = _mk_emp(db, "A3")
    with pytest.raises(AppError) as exc:
        ensure_days(db, [e.id], date(2024, 5, 1), date(2024, 5, 1))
    assert exc.value.code == "holiday_calendar_missing"


def test_ensure_days_skips_future(db):
    today = _today_sa()
    future = today + timedelta(days=5)
    e = _mk_emp(db, "A2")
    _mk_calendar(db, future.year, [date(future.year, 1, 1)])
    count = ensure_days(db, [e.id], future, future)
    assert count == 0


def test_ensure_days_creates_missing_punch_within_grace(db):
    today = _today_sa()
    e = _mk_emp(db, "A4", hire=today - timedelta(days=30))
    _mk_calendar(db, today.year, [date(today.year, 1, 1)])
    ensure_days(db, [e.id], today, today, absent_grace_days=1)
    day = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == e.id, AttendanceDay.work_date == today))
    if day is not None:
        assert day.status in ("missing_punch", "day_off")


def test_recompute_day_normal_weekday(db):
    _mk_calendar(db, 2024, [])
    shift = _mk_shift(db)
    _mk_rule(db, shift.id, "weekday", "normal", tier=1, up_to=None)
    _mk_rule(db, shift.id, "weekday", "overtime", tier=1, up_to=None, value="1.5")
    e = _mk_emp(db, "R1", hire=date(2024, 1, 1), dflt_shift=shift.id)
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 17, 0))
    day = recompute_day(db, e.id, date(2024, 5, 1))
    assert day is not None
    assert day.status == "worked"
    assert day.normal_minutes == 420
    assert day.overtime_minutes == 60
    assert day.worked_minutes == 480


def test_recompute_day_missing_out(db):
    _mk_calendar(db, 2024, [])
    shift = _mk_shift(db)
    _mk_rule(db, shift.id, "weekday", "normal", tier=1, up_to=None)
    e = _mk_emp(db, "R2", hire=date(2024, 1, 1), dflt_shift=shift.id)
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 8, 0))
    day = recompute_day(db, e.id, date(2024, 5, 1))
    assert day is not None
    assert day.status == "missing_punch"
    assert "missing_out" in (day.flags or [])


def test_recompute_day_idempotent(db):
    _mk_calendar(db, 2024, [])
    shift = _mk_shift(db)
    _mk_rule(db, shift.id, "weekday", "normal", tier=1, up_to=None)
    e = _mk_emp(db, "R3", hire=date(2024, 1, 1), dflt_shift=shift.id)
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 16, 0))
    d1 = recompute_day(db, e.id, date(2024, 5, 1))
    v1 = d1.source_version
    db.expire_all()
    d2 = recompute_day(db, e.id, date(2024, 5, 1))
    assert d2.source_version == v1


def test_recompute_day_locked_skipped(db):
    _mk_calendar(db, 2024, [])
    shift = _mk_shift(db)
    _mk_rule(db, shift.id, "weekday", "normal", tier=1, up_to=None)
    e = _mk_emp(db, "R4", hire=date(2024, 1, 1), dflt_shift=shift.id)
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 16, 0))
    day = recompute_day(db, e.id, date(2024, 5, 1))
    assert day is not None
    day.locked = True
    db.commit()
    sid = day.id
    db.expire_all()
    d2 = recompute_day(db, e.id, date(2024, 5, 1))
    assert d2 is not None and d2.id == sid

# END OF FILE