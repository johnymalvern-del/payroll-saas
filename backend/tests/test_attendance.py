"""Attendance endpoint tests (Chapter 2B)."""
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
    slug = f"att-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="Att Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
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


def _mk_emp(session, code, *, hire=None, dflt_shift=None):
    e = Employee(employee_code=code, first_name="A", last_name=code, hire_date=hire or date(2024, 1, 1), status="active", employee_type="hourly", pay_basis="hourly", pay_frequency="monthly", default_shift_id=dflt_shift, row_version=1)
    session.add(e); session.commit(); return e


def _mk_shift(session):
    s = Shift(name=f"S-{uuid.uuid4().hex[:6]}", start_time=time(8, 0), length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0, grace_late_minutes=0, grace_early_minutes=0, grace_mode="threshold", rounding_minutes=0, rounding_mode="nearest", min_overtime_minutes=0, overtime_requires_approval=False, max_shift_minutes=720, match_tolerance_minutes=60, salaried_premium_mode="full", pay_early_arrival=False, is_active=True, row_version=1)
    session.add(s); session.commit(); return s


def _mk_rule(session, shift_id, day_type="weekday", kind="normal"):
    r = ShiftRateRule(shift_id=shift_id, day_type=day_type, kind=kind, tier=1, tier_up_to_minutes=None, method="multiplier", value=Decimal("1.0"), flat_unit=None, effective_from=date(2020, 1, 1), effective_to=None)
    session.add(r); session.commit(); return r


def _mk_cal(session, year):
    session.add(CountryCalendar(country_code="ZA", holiday_date=date(year, 12, 25), name="Xmas", source_ref="test"))
    session.commit()


def _mk_punch(session, employee_id, ts_utc):
    p = Punch(client_punch_id=uuid.uuid4(), payload_hash="0"*64, employee_id=employee_id, device_time=ts_utc, effective_time=ts_utc, offset_ms=0, method="fingerprint", status="accepted", flags=[], raw_payload={})
    session.add(p); session.commit(); return p


def _mk_day(session, employee_id, work_date, *, status="worked", normal=480, locked=False, shift_id=None):
    d = AttendanceDay(employee_id=employee_id, work_date=work_date, status=status, normal_minutes=normal, worked_minutes=normal, overtime_minutes=0, raw_minutes=normal, shift_id=shift_id, flags=[], source_version=0, locked=locked, row_version=1)
    session.add(d); session.commit(); return d


def _sa_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=SA).astimezone(timezone.utc)


def test_list_requires_auth(api):
    client, tenant = api
    r = client.get("/api/v1/attendance/day", headers={"X-Tenant-Slug": tenant.slug})
    assert r.status_code == 401, r.text


def test_list_admin_ok_include_total(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    e = _mk_emp(db, "A1")
    _mk_day(db, e.id, date(2024, 5, 1))
    _mk_day(db, e.id, date(2024, 5, 2))
    r = client.get("/api/v1/attendance/day?include_total=true", headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_auditor_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username="aud-att", role="auditor", password="AudAttPass1234!")
    tok = _login(client, tenant.slug, "aud-att", "AudAttPass1234!")
    r = client.get("/api/v1/attendance/day", headers=_auth(tok, tenant.slug))
    assert r.status_code == 403, r.text


def test_list_employee_sees_own_only(api, db):
    client, tenant = api
    me = _mk_emp(db, "ME")
    other = _mk_emp(db, "OTHER")
    _mk_day(db, me.id, date(2024, 5, 1))
    _mk_day(db, other.id, date(2024, 5, 1))
    _mk_user(db, username="emp-att", role="employee", password="EmpAttPass1234!", employee_id=me.id)
    tok = _login(client, tenant.slug, "emp-att", "EmpAttPass1234!")
    r = client.get("/api/v1/attendance/day", headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["employee_id"] == str(me.id)


def test_detail_ok_with_segments(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    e = _mk_emp(db, "D1", dflt_shift=shift.id)
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 16, 0))
    recompute_day(db, e.id, date(2024, 5, 1))
    r = client.get(f"/api/v1/attendance/day/{e.id}/2024-05-01", headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "worked"
    assert len(body["segments"]) >= 1


def test_detail_unknown_404(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.get(f"/api/v1/attendance/day/{uuid.uuid4()}/2024-05-01", headers=_auth(tok, tenant.slug))
    assert r.status_code == 404, r.text


def test_recompute_payroll_admin_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    e = _mk_emp(db, "R1", dflt_shift=shift.id)
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 16, 0))
    r = client.post("/api/v1/attendance/recompute", headers=_auth(tok, tenant.slug), json={"employee_id": str(e.id), "from_date": "2024-05-01", "to_date": "2024-05-01"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recomputed"] == 1
    assert body["employee_count"] == 1


def test_recompute_employee_forbidden(api, db):
    client, tenant = api
    e = _mk_emp(db, "R2")
    _mk_user(db, username="emp-r", role="employee", password="EmpRPass12345!", employee_id=e.id)
    tok = _login(client, tenant.slug, "emp-r", "EmpRPass12345!")
    r = client.post("/api/v1/attendance/recompute", headers=_auth(tok, tenant.slug), json={"employee_id": str(e.id), "from_date": "2024-05-01", "to_date": "2024-05-01"})
    assert r.status_code == 403, r.text


def test_recompute_locked_skipped(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    _mk_rule(db, shift.id)
    e = _mk_emp(db, "L1", dflt_shift=shift.id)
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(db, e.id, _sa_utc(2024, 5, 1, 16, 0))
    recompute_day(db, e.id, date(2024, 5, 1))
    day = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == e.id, AttendanceDay.work_date == date(2024, 5, 1)))
    day.locked = True
    db.commit()
    r = client.post("/api/v1/attendance/recompute", headers=_auth(tok, tenant.slug), json={"employee_id": str(e.id), "from_date": "2024-05-01", "to_date": "2024-05-01"})
    assert r.status_code == 200, r.text
    assert r.json()["skipped_locked"] == 1

# END OF FILE