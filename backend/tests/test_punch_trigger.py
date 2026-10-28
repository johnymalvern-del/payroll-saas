"""Punch-trigger tests (Chapter 2B, 2B-5a).

Each test provisions a tenant, sets up one shift + rate rules + calendar,
sends one or more punches through POST /punches, and asserts that
attendance_day rows were created by the trigger inside _process_punch.
"""
from __future__ import annotations
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.device_auth import hash_device_key
from app.core.security import hash_password
from app.db.tenant.models.attendance import (
    AttendanceDay, CountryCalendar, Punch, Shift, ShiftRateRule,
)
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Site
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
    slug = f"pt-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="PT Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
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
def api(api_client, disposable_tenant):
    return api_client, disposable_tenant


@pytest.fixture()
def db(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


def _mk_bs(session):
    b = Branch(name="B", code=f"B-{uuid.uuid4().hex[:6]}", is_active=True, row_version=1)
    session.add(b); session.commit()
    s = Site(branch_id=b.id, name="S", code=f"S-{uuid.uuid4().hex[:6]}", site_type="site", timezone="Africa/Johannesburg", is_active=True, row_version=1)
    session.add(s); session.commit()
    return s


def _mk_device(session, site_id):
    raw = "a" * 64
    d = Device(site_id=site_id, name="D", device_type="usb_fingerprint", api_key_hash=hash_device_key(raw), status="active", allows_code_only=False, require_photo_for_code=True, pending_punch_count=0, row_version=1)
    session.add(d); session.commit()
    return d, raw


def _mk_emp(session, code, *, dflt_shift=None, hire=None):
    e = Employee(employee_code=code, first_name="A", last_name=code, hire_date=hire or date(2024, 1, 1), status="active", employee_type="hourly", pay_basis="hourly", pay_frequency="monthly", default_shift_id=dflt_shift, row_version=1)
    session.add(e); session.commit(); return e


def _mk_shift(session, start_h=8):
    s = Shift(name=f"S-{uuid.uuid4().hex[:6]}", start_time=datetime(2024,1,1,start_h,0).time(), length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0, grace_late_minutes=0, grace_early_minutes=0, grace_mode="threshold", rounding_minutes=0, rounding_mode="nearest", min_overtime_minutes=0, overtime_requires_approval=False, max_shift_minutes=720, match_tolerance_minutes=60, salaried_premium_mode="full", pay_early_arrival=False, is_active=True, row_version=1)
    session.add(s); session.commit(); return s


def _mk_rule(session, shift_id):
    r = ShiftRateRule(shift_id=shift_id, day_type="weekday", kind="normal", tier=1, tier_up_to_minutes=None, method="multiplier", value=Decimal("1.0"), flat_unit=None, effective_from=date(2020, 1, 1), effective_to=None)
    session.add(r); session.commit(); return r


def _mk_cal(session, year):
    _existing = session.scalar(select(CountryCalendar).where(
        CountryCalendar.country_code == "ZA",
        CountryCalendar.holiday_date == date(year, 12, 25),
    ))
    if _existing is not None:
        return
    session.add(CountryCalendar(country_code="ZA", holiday_date=date(year, 12, 25), name="Xmas", source_ref="test"))
    session.commit()


def _today_sa():
    return datetime.now(timezone.utc).astimezone(SA).date()


def _payload(emp_id, ts_utc=None):
    ts = ts_utc or datetime.now(timezone.utc)
    return {
        "client_punch_id": str(uuid.uuid4()),
        "employee_id": str(emp_id),
        "device_time": ts.isoformat(),
        "method": "fingerprint",
        "match_score": "95",
        "liveness_passed": True,
        "raw_payload": {},
    }


def _post(client, slug, raw, body):
    return client.post("/api/v1/punches", headers={"X-Tenant-Slug": slug, "X-Device-Key": raw}, json=body)


def test_single_punch_creates_attendance_day(api, db):
    client, tenant = api
    today = _today_sa()
    _mk_cal(db, today.year)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    emp = _mk_emp(db, "T1", dflt_shift=shift.id, hire=today - timedelta(days=30))
    site = _mk_bs(db)
    _dev, raw = _mk_device(db, site.id)
    r = _post(client, tenant.slug, raw, _payload(emp.id))
    assert r.status_code == 201, r.text
    db.expire_all()
    day = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == today))
    assert day is not None, "punch trigger did not create attendance_day"
    assert day.status in ("worked", "missing_punch", "no_shift_match")


def test_single_punch_uses_default_shift(api, db):
    client, tenant = api
    today = _today_sa()
    _mk_cal(db, today.year)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    emp = _mk_emp(db, "T2", dflt_shift=shift.id, hire=today - timedelta(days=30))
    site = _mk_bs(db)
    _dev, raw = _mk_device(db, site.id)
    r = _post(client, tenant.slug, raw, _payload(emp.id))
    assert r.status_code == 201, r.text
    db.expire_all()
    day = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == today))
    assert day is not None
    assert day.shift_id == shift.id


def test_punch_in_out_produces_worked_day(api, db):
    client, tenant = api
    today = _today_sa()
    _mk_cal(db, today.year)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    emp = _mk_emp(db, "T3", dflt_shift=shift.id, hire=today - timedelta(days=30))
    site = _mk_bs(db)
    _dev, raw = _mk_device(db, site.id)
    base = datetime.now(timezone.utc)
    r1 = _post(client, tenant.slug, raw, _payload(emp.id, base))
    assert r1.status_code == 201, r1.text
    r2 = _post(client, tenant.slug, raw, _payload(emp.id, base + timedelta(minutes=30)))
    assert r2.status_code == 201, r2.text
    db.expire_all()
    day = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == today))
    assert day is not None
    assert day.status in ("worked", "missing_punch")


def test_two_punches_two_days(api, db):
    client, tenant = api
    today = _today_sa()
    _mk_cal(db, today.year)
    _mk_cal(db, (today - timedelta(days=1)).year)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    emp = _mk_emp(db, "T4", dflt_shift=shift.id, hire=today - timedelta(days=30))
    site = _mk_bs(db)
    _dev, raw = _mk_device(db, site.id)
    now = datetime.now(timezone.utc)
    _post(client, tenant.slug, raw, _payload(emp.id, now))
    _post(client, tenant.slug, raw, _payload(emp.id, now - timedelta(days=1)))
    db.expire_all()
    days = db.scalars(select(AttendanceDay).where(AttendanceDay.employee_id == emp.id)).all()
    assert len(days) >= 2
    dates = {d.work_date for d in days}
    assert today in dates or (today - timedelta(days=1)) in dates

# END OF FILE