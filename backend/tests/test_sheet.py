"""Sheet endpoint tests (Chapter 2C, 2C-5d). Part 1 of 2.

Part 1: fixtures, helpers, and 2 tests (basic sheet, C2 any-role).
Part 2 (2C-5d-ii) appends daily, mark_reviewed, and mark_reviewed-refusal.
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
    slug = f"sht-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="Sheet Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
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
    r = client.post("/api/v1/auth/login", headers={"X-Tenant-Slug": slug}, json={"identifier": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token, slug):
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": slug}


def _admin_token(client, slug):
    token = _login(client, slug, "admin", "TestPassword123!")
    r = client.post("/api/v1/auth/change-password", headers={**_auth(token, slug), "Content-Type": "application/json"}, json={"current_password": "TestPassword123!", "new_password": "PostChange123!"})
    assert r.status_code in (200, 204), r.text
    return _login(client, slug, "admin", "PostChange123!")


def _mk_user(session, *, username, role, password, employee_id=None):
    u = User(username=normalise_username(username), password_hash=hash_password(password), role=role, is_active=True, must_change_password=False, employee_id=employee_id, row_version=1)
    session.add(u); session.commit(); return u


def _mk_emp(session, code, *, dflt_shift=None):
    e = Employee(employee_code=code, first_name="A", last_name=code, hire_date=date(2024, 1, 1), status="active", employee_type="hourly", pay_basis="hourly", pay_frequency="monthly", default_shift_id=dflt_shift, row_version=1)
    session.add(e); session.commit(); return e


def _mk_shift(session):
    s = Shift(name=f"S-{uuid.uuid4().hex[:6]}", start_time=time(8, 0), length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0, grace_late_minutes=0, grace_early_minutes=0, grace_mode="threshold", rounding_minutes=0, rounding_mode="nearest", min_overtime_minutes=0, overtime_requires_approval=False, max_shift_minutes=720, match_tolerance_minutes=60, salaried_premium_mode="full", pay_early_arrival=False, is_active=True, row_version=1)
    session.add(s); session.commit(); return s


def _mk_rule(session, shift_id):
    r = ShiftRateRule(shift_id=shift_id, day_type="weekday", kind="normal", tier=1, tier_up_to_minutes=None, method="multiplier", value=Decimal("1.0"), flat_unit=None, effective_from=date(2020, 1, 1), effective_to=None)
    session.add(r); session.commit(); return r


def _mk_cal(session, year):
    target = date(year, 12, 25)
    if session.scalar(select(CountryCalendar).where(CountryCalendar.country_code == "ZA", CountryCalendar.holiday_date == target)) is not None:
        return
    session.add(CountryCalendar(country_code="ZA", holiday_date=target, name="Xmas", source_ref="test"))
    session.commit()


def _mk_punch(session, employee_id, ts_utc):
    p = Punch(client_punch_id=uuid.uuid4(), payload_hash="0"*64, employee_id=employee_id, device_time=ts_utc, effective_time=ts_utc, offset_ms=0, method="fingerprint", status="accepted", flags=[], raw_payload={})
    session.add(p); session.commit(); return p


def _sa_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=SA).astimezone(timezone.utc)


def _setup_worked_day(session, code="SH1"):
    _mk_cal(session, 2024)
    shift = _mk_shift(session)
    _mk_rule(session, shift.id)
    emp = _mk_emp(session, code, dflt_shift=shift.id)
    _mk_punch(session, emp.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(session, emp.id, _sa_utc(2024, 5, 1, 17, 0))
    recompute_day(session, emp.id, date(2024, 5, 1))
    return emp, shift


def _apply_leave_adjustment(client, slug, token, employee_id):
    r = client.post(
        "/api/v1/attendance/adjustments",
        headers=_auth(token, slug),
        json={
            "employee_id": str(employee_id),
            "work_date": "2024-05-01",
            "outcome": "leave",
            "reason_code": "system_correction",
            "note": "Test leave overlay",
        },
    )
    assert r.status_code == 201, r.text


_FORBIDDEN_KEYS = {"adjusted", "adjustment", "adjustment_id", "reason_code"}


def _assert_no_adjustment_fields(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in _FORBIDDEN_KEYS, f"forbidden key '{k}' at {path or 'root'}"
            if k == "flags" and isinstance(v, list):
                for flag in v:
                    if isinstance(flag, str):
                        assert "adjust" not in flag.lower(), f"forbidden flag '{flag}' at {path}.flags"
            _assert_no_adjustment_fields(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_adjustment_fields(v, f"{path}[{i}]")


def test_sheet_basic_structure(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_worked_day(db)
    r = client.get(
        "/api/v1/attendance/sheet?from_date=2024-05-01&to_date=2024-05-01",
        headers=_auth(tok, tenant.slug),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["employee_id"] == str(emp.id)
    assert item["employee_code"] == "SH1"
    assert "employee_name" in item
    assert len(item["days"]) == 1
    cell = item["days"][0]
    assert cell["work_date"] == "2024-05-01"
    assert cell["status"] == "worked"
    assert cell["normal_minutes"] == 420
    assert cell["overtime_minutes"] == 60
    assert cell["worked_minutes"] == 480
    assert cell["locked"] is False
    assert cell["reviewed"] is False


def test_sheet_no_adjustment_fields_any_role(api, db):
    """C2: adjusted days look identical to clocked days. No field named
    adjusted/adjustment/adjustment_id/reason_code appears in the response for
    any role that reaches the endpoint (auditor gets 403 and is vacuously OK).
    Uses an actual adjusted day (leave) as the payload.
    """
    client, tenant = api
    admin_tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_worked_day(db, code="C2-1")
    _apply_leave_adjustment(client, tenant.slug, admin_tok, emp.id)

    _mk_user(db, username="sht-pa", role="payroll_admin", password="ShtPa12345678!")
    _mk_user(db, username="sht-hr", role="hr", password="ShtHr12345678!")
    _mk_user(db, username="sht-mgr", role="manager", password="ShtMgr12345678!")
    _mk_user(db, username="sht-emp", role="employee", password="ShtEmp12345678!", employee_id=emp.id)
    _mk_user(db, username="sht-aud", role="auditor", password="ShtAud12345678!")

    roles = [
        ("payroll_admin", "sht-pa", "ShtPa12345678!"),
        ("hr", "sht-hr", "ShtHr12345678!"),
        ("manager", "sht-mgr", "ShtMgr12345678!"),
        ("employee", "sht-emp", "ShtEmp12345678!"),
        ("auditor", "sht-aud", "ShtAud12345678!"),
    ]
    for role, uname, pwd in roles:
        tok = _login(client, tenant.slug, uname, pwd)
        r = client.get(
            "/api/v1/attendance/sheet?from_date=2024-05-01&to_date=2024-05-01",
            headers=_auth(tok, tenant.slug),
        )
        assert r.status_code in (200, 403), f"{role}: unexpected {r.status_code}: {r.text}"
        if r.status_code == 200:
            body = r.json()
            _assert_no_adjustment_fields(body, path=role)
            # For roles that see the adjusted employee, the cell status must be
            # plain 'leave', not 'adjusted' or 'leave_adjusted' or similar.
            for item in body["items"]:
                if item["employee_id"] == str(emp.id):
                    assert item["days"][0]["status"] == "leave", (
                        f"{role}: adjusted day cell shows {item['days'][0]['status']!r}, expected 'leave'"
                    )

# END OF FILE