"""Adjustment endpoint tests (Chapter 2C, 2C-4d-ii).

Part 1: fixtures, helpers, and 4 single-adjustment tests.
Part 2 (2C-4d-ii-b) appends revert, audit, and 2 bulk tests.
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
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import (
    AttendanceDay, CountryCalendar, Punch, Shift, ShiftRateRule,
)
from app.db.tenant.models.people import Employee, User
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
    slug = f"adj-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="Adj Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
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


def _login(client, slug, username, password):
    r = client.post("/api/v1/auth/login",
                    headers={"X-Tenant-Slug": slug},
                    json={"identifier": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token, slug):
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": slug}


def _admin_token(client, slug):
    token = _login(client, slug, "admin", "TestPassword123!")
    r = client.post("/api/v1/auth/change-password",
                    headers={**_auth(token, slug), "Content-Type": "application/json"},
                    json={"current_password": "TestPassword123!", "new_password": "PostChange123!"})
    assert r.status_code in (200, 204), r.text
    return _login(client, slug, "admin", "PostChange123!")


def _mk_user(session, *, username, role, password, employee_id=None):
    u = User(username=normalise_username(username), password_hash=hash_password(password),
             role=role, is_active=True, must_change_password=False,
             employee_id=employee_id, row_version=1)
    session.add(u); session.commit(); return u


def _mk_emp(session, code, *, dflt_shift=None):
    e = Employee(employee_code=code, first_name="A", last_name=code,
                 hire_date=date(2024, 1, 1), status="active",
                 employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
                 default_shift_id=dflt_shift, row_version=1)
    session.add(e); session.commit(); return e


def _mk_shift(session):
    s = Shift(name=f"S-{uuid.uuid4().hex[:6]}", start_time=time(8, 0),
              length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0,
              grace_late_minutes=0, grace_early_minutes=0, grace_mode="threshold",
              rounding_minutes=0, rounding_mode="nearest",
              min_overtime_minutes=0, overtime_requires_approval=True,
              max_shift_minutes=720, match_tolerance_minutes=60,
              salaried_premium_mode="full", pay_early_arrival=False,
              is_active=True, row_version=1)
    session.add(s); session.commit(); return s


def _mk_rule(session, shift_id):
    r = ShiftRateRule(shift_id=shift_id, day_type="weekday", kind="normal", tier=1,
                      tier_up_to_minutes=None, method="multiplier",
                      value=Decimal("1.0"), flat_unit=None,
                      effective_from=date(2020, 1, 1), effective_to=None)
    session.add(r); session.commit(); return r


def _mk_cal(session, year):
    target = date(year, 12, 25)
    if session.scalar(select(CountryCalendar).where(
        CountryCalendar.country_code == "ZA",
        CountryCalendar.holiday_date == target,
    )) is not None:
        return
    session.add(CountryCalendar(country_code="ZA", holiday_date=target,
                                name="Xmas", source_ref="test"))
    session.commit()


def _mk_punch(session, employee_id, ts_utc):
    p = Punch(client_punch_id=uuid.uuid4(), payload_hash="0"*64,
              employee_id=employee_id, device_time=ts_utc,
              effective_time=ts_utc, offset_ms=0, method="fingerprint",
              status="accepted", flags=[], raw_payload={})
    session.add(p); session.commit(); return p


def _sa_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=SA).astimezone(timezone.utc)


def _adj_payload(employee_id, work_date, outcome, time_in=None, time_out=None,
                 reason_code="forgot_clock", note=None):
    return {
        "employee_id": str(employee_id),
        "work_date": work_date.isoformat(),
        "outcome": outcome,
        "time_in": time_in.isoformat() if time_in else None,
        "time_out": time_out.isoformat() if time_out else None,
        "reason_code": reason_code,
        "note": note,
    }


def _setup_normal_day(db, code, day=date(2024, 5, 1)):
    _mk_cal(db, day.year)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    emp = _mk_emp(db, code, dflt_shift=shift.id)
    _mk_punch(db, emp.id, _sa_utc(day.year, day.month, day.day, 8, 0))
    _mk_punch(db, emp.id, _sa_utc(day.year, day.month, day.day, 17, 0))
    recompute_day(db, emp.id, day)
    return emp, shift


def test_single_adjustment_worked_overrides_punches(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_normal_day(db, "W1")
    payload = _adj_payload(emp.id, date(2024, 5, 1), "worked",
                           time_in=_sa_utc(2024, 5, 1, 8, 0),
                           time_out=_sa_utc(2024, 5, 1, 18, 0))
    r = client.post("/api/v1/attendance/adjustments",
                    headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["day_normal_minutes"] == 420
    assert body["day_overtime_minutes"] == 120
    assert body["day_worked_minutes"] == 540


def test_single_adjustment_locked_day_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_normal_day(db, "LK1")
    day = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp.id,
        AttendanceDay.work_date == date(2024, 5, 1),
    ))
    day.locked = True
    db.commit()
    payload = _adj_payload(emp.id, date(2024, 5, 1), "day_off",
                           reason_code="system_correction")
    r = client.post("/api/v1/attendance/adjustments",
                    headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "day_locked"
    assert "closed" in r.json()["error"]["message"].lower()


def test_single_adjustment_self_adjust_403(api, db):
    client, tenant = api
    emp = _mk_emp(db, "SA1")
    _mk_cal(db, 2024)
    _mk_user(db, username="hr-self", role="hr", password="HrSelfPass1234!",
             employee_id=emp.id)
    tok = _login(client, tenant.slug, "hr-self", "HrSelfPass1234!")
    payload = _adj_payload(emp.id, date(2024, 5, 1), "day_off",
                           reason_code="system_correction")
    r = client.post("/api/v1/attendance/adjustments",
                    headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "cannot_adjust_own"


def test_bulk_dry_run_and_apply_happy_path(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp1, _ = _setup_normal_day(db, "B1")
    emp2, _ = _setup_normal_day(db, "B2")
    items = [
        _adj_payload(emp1.id, date(2024, 5, 1), "day_off",
                     reason_code="system_correction"),
        _adj_payload(emp2.id, date(2024, 5, 1), "day_off",
                     reason_code="system_correction"),
    ]
    r1 = client.post("/api/v1/attendance/adjustments/bulk",
                     headers=_auth(tok, tenant.slug), json={"items": items})
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["dry_run"] is True
    assert body1["applied"] == 0
    assert len(body1["token"]) == 64
    token = body1["token"]
    db.expire_all()
    day1 = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp1.id,
        AttendanceDay.work_date == date(2024, 5, 1),
    ))
    assert day1.status == "worked"
    r2 = client.post("/api/v1/attendance/adjustments/bulk",
                     headers=_auth(tok, tenant.slug),
                     json={"items": items, "token": token})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["dry_run"] is False
    assert body2["applied"] == 2
    db.expire_all()
    day1b = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp1.id,
        AttendanceDay.work_date == date(2024, 5, 1),
    ))
    assert day1b.status == "day_off"


def test_single_adjustment_leave_sets_unreconciled_flag(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_normal_day(db, "LV1")
    payload = _adj_payload(emp.id, date(2024, 5, 1), "leave",
                           reason_code="system_correction",
                           note="HR recorded yesterday's leave")
    r = client.post("/api/v1/attendance/adjustments",
                    headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["day_status"] == "leave"
    assert body["day_worked_minutes"] == 0
    day = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp.id,
        AttendanceDay.work_date == date(2024, 5, 1),
    ))
    assert day.status == "leave"
    assert "unreconciled_leave" in (day.flags or [])


def test_single_adjustment_revert_restores_punch_based(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_normal_day(db, "RV1")
    # First adjustment: change to day_off
    payload_off = _adj_payload(emp.id, date(2024, 5, 1), "day_off",
                               reason_code="system_correction")
    r1 = client.post("/api/v1/attendance/adjustments",
                     headers=_auth(tok, tenant.slug), json=payload_off)
    assert r1.status_code == 201, r1.text
    assert r1.json()["day_status"] == "day_off"
    # Revert: back to punches
    payload_revert = _adj_payload(emp.id, date(2024, 5, 1), "revert",
                                  reason_code="system_correction")
    r2 = client.post("/api/v1/attendance/adjustments",
                     headers=_auth(tok, tenant.slug), json=payload_revert)
    assert r2.status_code == 201, r2.text
    body2 = r2.json()
    assert body2["day_status"] == "worked"
    assert body2["day_normal_minutes"] == 420
    assert body2["day_overtime_minutes"] == 60


def test_single_adjustment_audit_old_new_and_day_snapshot(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_normal_day(db, "AU1")
    payload = _adj_payload(emp.id, date(2024, 5, 1), "day_off",
                           reason_code="system_correction")
    r = client.post("/api/v1/attendance/adjustments",
                    headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text
    adj_id = r.json()["adjustment"]["id"]
    from app.db.tenant.models.platform import AuditLog
    audit = db.scalar(select(AuditLog).where(
        AuditLog.entity_type == "adjustment",
        AuditLog.entity_id == adj_id,
        AuditLog.action == "attendance.adjustment.create",
    ))
    assert audit is not None
    assert audit.old_value is not None
    assert audit.old_value.get("status") == "worked"
    assert audit.new_value is not None
    assert "adjustment" in audit.new_value
    assert "day" in audit.new_value
    assert audit.new_value["day"].get("status") == "day_off"
    assert audit.new_value["adjustment"].get("outcome") == "day_off"


def test_bulk_apply_all_or_nothing_on_pre_validation(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp1, _ = _setup_normal_day(db, "BL1")
    emp2, _ = _setup_normal_day(db, "BL2")
    # Lock emp2's day -> bulk must fail pre-validation
    day2 = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp2.id,
        AttendanceDay.work_date == date(2024, 5, 1),
    ))
    day2.locked = True
    db.commit()
    items = [
        _adj_payload(emp1.id, date(2024, 5, 1), "day_off",
                     reason_code="system_correction"),
        _adj_payload(emp2.id, date(2024, 5, 1), "day_off",
                     reason_code="system_correction"),
    ]
    r1 = client.post("/api/v1/attendance/adjustments/bulk",
                     headers=_auth(tok, tenant.slug), json={"items": items})
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["dry_run"] is True
    assert body1["results"][0]["ok"] is True
    assert body1["results"][1]["ok"] is False
    assert body1["results"][1]["error_code"] == "day_locked"
    token = body1["token"]
    # Real call with valid token -> 400 bulk_validation_failed, nothing applied
    r2 = client.post("/api/v1/attendance/adjustments/bulk",
                     headers=_auth(tok, tenant.slug),
                     json={"items": items, "token": token})
    assert r2.status_code == 400, r2.text
    assert r2.json()["error"]["code"] == "bulk_validation_failed"
    db.expire_all()
    day1b = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp1.id,
        AttendanceDay.work_date == date(2024, 5, 1),
    ))
    assert day1b.status == "worked"

# END OF FILE
