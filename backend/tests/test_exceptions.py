"""Exceptions queue endpoint tests (Chapter 2C, 2C-3c)."""
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
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import (
    AttendanceDay, CountryCalendar, ExceptionItem, Punch, Shift, ShiftRateRule,
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
    slug = f"exc-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="Exc Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
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
    s = Shift(name=f"S-{uuid.uuid4().hex[:6]}", start_time=time(8, 0), length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0, grace_late_minutes=0, grace_early_minutes=0, grace_mode="threshold", rounding_minutes=0, rounding_mode="nearest", min_overtime_minutes=0, overtime_requires_approval=True, max_shift_minutes=720, match_tolerance_minutes=60, salaried_premium_mode="full", pay_early_arrival=False, is_active=True, row_version=1)
    session.add(s); session.commit(); return s


def _mk_rule(session, shift_id):
    r = ShiftRateRule(shift_id=shift_id, day_type="weekday", kind="normal", tier=1, tier_up_to_minutes=None, method="multiplier", value=Decimal("1.0"), flat_unit=None, effective_from=date(2020, 1, 1), effective_to=None)
    session.add(r); session.commit(); return r


def _mk_cal(session, year):
    session.add(CountryCalendar(country_code="ZA", holiday_date=date(year, 12, 25), name="Xmas", source_ref="test"))
    session.commit()


def _mk_punch(session, employee_id, ts_utc):
    p = Punch(client_punch_id=uuid.uuid4(), payload_hash="0"*64, employee_id=employee_id, device_time=ts_utc, effective_time=ts_utc, offset_ms=0, method="fingerprint", status="accepted", flags=[], raw_payload={})
    session.add(p); session.commit(); return p


def _mk_open_exception(session, employee_id, work_date, exc_type):
    e = ExceptionItem(employee_id=employee_id, work_date=work_date, type=exc_type, source_ref={}, suggested_fix={}, status="open")
    session.add(e); session.commit(); return e


def _sa_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=SA).astimezone(timezone.utc)


def test_list_requires_auth(api):
    client, tenant = api
    r = client.get("/api/v1/attendance/exceptions", headers={"X-Tenant-Slug": tenant.slug})
    assert r.status_code == 401, r.text


def test_list_admin_ok_include_total(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    e = _mk_emp(db, "L1")
    _mk_open_exception(db, e.id, date(2024, 5, 1), "missing_out")
    _mk_open_exception(db, e.id, date(2024, 5, 2), "absent_expected")
    r = client.get("/api/v1/attendance/exceptions?include_total=true", headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_filters_by_type(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    e = _mk_emp(db, "L2")
    _mk_open_exception(db, e.id, date(2024, 5, 1), "missing_out")
    _mk_open_exception(db, e.id, date(2024, 5, 2), "absent_expected")
    r = client.get("/api/v1/attendance/exceptions?type=missing_out", headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["type"] == "missing_out"


def test_get_unknown_404(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.get(f"/api/v1/attendance/exceptions/{uuid.uuid4()}", headers=_auth(tok, tenant.slug))
    assert r.status_code == 404, r.text


def test_resolve_dismiss_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    e = _mk_emp(db, "D1")
    exc = _mk_open_exception(db, e.id, date(2024, 5, 1), "low_confidence")
    r = client.post(
        f"/api/v1/attendance/exceptions/{exc.id}/resolve",
        headers=_auth(tok, tenant.slug),
        json={"action": "dismiss", "note": "User confirmed punch"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exception"]["status"] == "resolved"
    assert body["adjustment_id"] is None


def test_resolve_dismiss_requires_note(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    e = _mk_emp(db, "D2")
    exc = _mk_open_exception(db, e.id, date(2024, 5, 1), "low_confidence")
    r = client.post(
        f"/api/v1/attendance/exceptions/{exc.id}/resolve",
        headers=_auth(tok, tenant.slug),
        json={"action": "dismiss"},
    )
    assert r.status_code == 422, r.text


def test_bulk_dry_run_returns_token_no_writes(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    e = _mk_emp(db, "B1")
    exc1 = _mk_open_exception(db, e.id, date(2024, 5, 1), "low_confidence")
    exc2 = _mk_open_exception(db, e.id, date(2024, 5, 2), "low_confidence")
    r = client.post(
        "/api/v1/attendance/exceptions/bulk_resolve",
        headers=_auth(tok, tenant.slug),
        json={"items": [
            {"exception_id": str(exc1.id), "action": "dismiss", "note": "note1"},
            {"exception_id": str(exc2.id), "action": "dismiss", "note": "note2"},
        ]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["applied"] == 0
    assert len(body["token"]) == 64
    db.expire_all()
    for exc in (exc1, exc2):
        refetched = db.get(ExceptionItem, exc.id)
        assert refetched.status == "open"

# END OF FILE