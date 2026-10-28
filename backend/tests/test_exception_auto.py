"""Exception creation tests (2C-2b-2b-ii)."""
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

from app.api.v1.attendance_engine import recompute_day
from app.core.security import hash_password
from app.db.tenant.models.attendance import (
    AttendanceDay, CountryCalendar, ExceptionItem, Punch,
    Shift, ShiftRateRule,
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
    slug = f"ex-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="EX Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
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


def _mk_emp(session, code, *, dflt_shift=None, hire=None):
    e = Employee(employee_code=code, first_name="A", last_name=code, hire_date=hire or date(2024, 1, 1), status="active", employee_type="hourly", pay_basis="hourly", pay_frequency="monthly", default_shift_id=dflt_shift, row_version=1)
    session.add(e); session.commit(); return e


def _mk_shift(session):
    s = Shift(name=f"S-{uuid.uuid4().hex[:6]}", start_time=time(8, 0), length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0, grace_late_minutes=0, grace_early_minutes=0, grace_mode="threshold", rounding_minutes=0, rounding_mode="nearest", min_overtime_minutes=0, overtime_requires_approval=True, max_shift_minutes=720, match_tolerance_minutes=60, salaried_premium_mode="full", pay_early_arrival=False, is_active=True, row_version=1)
    session.add(s); session.commit(); return s


def _mk_rule(session, shift_id, *, day_type="weekday", kind="normal", ot_status_hint=None):
    r = ShiftRateRule(shift_id=shift_id, day_type=day_type, kind=kind, tier=1, tier_up_to_minutes=None, method="multiplier", value=Decimal("1.0"), flat_unit=None, effective_from=date(2020, 1, 1), effective_to=None)
    session.add(r); session.commit(); return r


def _mk_cal(session, year):
    session.add(CountryCalendar(country_code="ZA", holiday_date=date(year, 12, 25), name="Xmas", source_ref="test"))
    session.commit()


def _mk_punch(session, employee_id, ts_utc, *, status="accepted"):
    p = Punch(client_punch_id=uuid.uuid4(), payload_hash="0"*64, employee_id=employee_id, device_time=ts_utc, effective_time=ts_utc, offset_ms=0, method="fingerprint", status=status, flags=[], raw_payload={})
    session.add(p); session.commit(); return p


def _sa_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=SA).astimezone(timezone.utc)


def _open_exception(db, employee_id, work_date, exc_type):
    return db.scalar(select(ExceptionItem).where(
        ExceptionItem.employee_id == employee_id,
        ExceptionItem.work_date == work_date,
        ExceptionItem.type == exc_type,
        ExceptionItem.status == "open",
    ))


def test_creates_missing_out_exception(db):
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    emp = _mk_emp(db, "M1", dflt_shift=shift.id)
    _mk_punch(db, emp.id, _sa_utc(2024, 5, 1, 8, 0))
    recompute_day(db, emp.id, date(2024, 5, 1))
    db.expire_all()
    day = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == date(2024, 5, 1)))
    assert day is not None and "missing_out" in (day.flags or [])
    exc = _open_exception(db, emp.id, date(2024, 5, 1), "missing_out")
    assert exc is not None
    assert exc.suggested_fix.get("action") == "apply_shift_end_time"


def test_creates_absent_expected_exception(db):
    _mk_cal(db, 2024)
    emp = _mk_emp(db, "A1", hire=date(2024, 1, 1))
    recompute_day(db, emp.id, date(2024, 5, 7))
    db.expire_all()
    day = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == date(2024, 5, 7)))
    assert day is not None and day.status == "absent"
    exc = _open_exception(db, emp.id, date(2024, 5, 7), "absent_expected")
    assert exc is not None


def test_creates_overtime_unapproved_exception(db):
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id, kind="normal")
    _mk_rule(db, shift.id, kind="overtime")
    emp = _mk_emp(db, "O1", dflt_shift=shift.id)
    _mk_punch(db, emp.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(db, emp.id, _sa_utc(2024, 5, 1, 18, 0))
    recompute_day(db, emp.id, date(2024, 5, 1))
    db.expire_all()
    exc = _open_exception(db, emp.id, date(2024, 5, 1), "overtime_unapproved")
    assert exc is not None
    assert exc.suggested_fix.get("action") == "approve_overtime"


def test_creates_low_confidence_exception(db):
    _mk_cal(db, 2024)
    emp = _mk_emp(db, "L1", hire=date(2024, 1, 1))
    _mk_punch(db, emp.id, _sa_utc(2024, 5, 1, 8, 0), status="low_confidence")
    recompute_day(db, emp.id, date(2024, 5, 1))
    db.expire_all()
    exc = _open_exception(db, emp.id, date(2024, 5, 1), "low_confidence")
    assert exc is not None
    assert exc.suggested_fix.get("action") == "accept_punch"


def test_creates_no_shift_match_exception(db):
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    emp = _mk_emp(db, "N1")
    _mk_punch(db, emp.id, _sa_utc(2024, 5, 1, 14, 0))
    recompute_day(db, emp.id, date(2024, 5, 1))
    db.expire_all()
    day = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == date(2024, 5, 1)))
    assert day is not None and day.status == "no_shift_match"
    exc = _open_exception(db, emp.id, date(2024, 5, 1), "no_shift_match")
    assert exc is not None

# END OF FILE
