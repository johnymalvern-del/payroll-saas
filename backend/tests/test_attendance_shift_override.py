"""Attendance shift-override tests (Stage B Batch C).

Covers the HR-selected shift override introduced in Stage B Batch C:
  - create_adjustment accepts shift_id in the payload, resolves it to a
    Shift row, rejects unknown ids with 400 invalid_shift before any write.
  - The override is stored on Adjustment.shift_id, and the shift's name
    is captured inside new_value.shift_name at write time so a later
    hard-delete of the Shift row (FK ON DELETE SET NULL) does not erase
    the label.
  - recompute_day applies the override to every session of the day
    (overriding detect_shift / default_shift_id / expected_shift_id).
  - A no-op recompute does not bump source_version (payroll comparison
    relies on this).
  - GET /attendance/adjustments/history returns shift_id and shift_name,
    newest first, with scope enforced (404 to out-of-scope callers).

Fixtures mirror test_adjustments.py: each test module is self-contained
(disposable tenant, api/db, the _mk_* helpers). No shared conftest.
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
    Adjustment, AttendanceDay, CountryCalendar, Punch, Shift, ShiftRateRule,
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
    slug = f"so-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="Shift Override Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
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


def _mk_shift(session, *, name=None, start_hour=8, length_minutes=480, unpaid_break_minutes=60, overtime_requires_approval=False):
    s = Shift(
        name=name or f"S-{uuid.uuid4().hex[:6]}",
        start_time=time(start_hour, 0),
        length_minutes=length_minutes,
        unpaid_break_minutes=unpaid_break_minutes,
        paid_break_minutes=0,
        grace_late_minutes=0, grace_early_minutes=0, grace_mode="threshold",
        rounding_minutes=0, rounding_mode="nearest",
        min_overtime_minutes=0, overtime_requires_approval=overtime_requires_approval,
        max_shift_minutes=max(720, length_minutes + 240),
        match_tolerance_minutes=60,
        salaried_premium_mode="full", pay_early_arrival=False,
        is_active=True, row_version=1,
    )
    session.add(s); session.commit(); return s


def _mk_rule(session, shift_id, *, value="1.0", kind="normal"):
    r = ShiftRateRule(shift_id=shift_id, day_type="weekday", kind=kind, tier=1, tier_up_to_minutes=None, method="multiplier", value=Decimal(value), flat_unit=None, effective_from=date(2020, 1, 1), effective_to=None)
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


def _adj_payload(employee_id, work_date, outcome, time_in=None, time_out=None, reason_code="forgot_clock", note=None, shift_id=None):
    payload = {
        "employee_id": str(employee_id),
        "work_date": work_date.isoformat(),
        "outcome": outcome,
        "time_in": time_in.isoformat() if time_in else None,
        "time_out": time_out.isoformat() if time_out else None,
        "reason_code": reason_code,
        "note": note,
    }
    if shift_id is not None:
        payload["shift_id"] = str(shift_id)
    return payload


def _setup_punch_day(db, code, *, shift=None, day=date(2024, 5, 1)):
    _mk_cal(db, day.year)
    shift = shift or _mk_shift(db)
    _mk_rule(db, shift.id)
    emp = _mk_emp(db, code, dflt_shift=shift.id)
    _mk_punch(db, emp.id, _sa_utc(day.year, day.month, day.day, 8, 0))
    _mk_punch(db, emp.id, _sa_utc(day.year, day.month, day.day, 17, 0))
    recompute_day(db, emp.id, day)
    return emp, shift


def test_create_adjustment_with_shift_id_records_override(api, db):
    """POST /attendance/adjustments with shift_id -> 201; row + snapshot populated."""
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_punch_day(db, "SO1")
    override = _mk_shift(db, name="Override-Day", start_hour=9, length_minutes=480)
    _mk_rule(db, override.id)

    payload = _adj_payload(
        emp.id, date(2024, 5, 1), "worked",
        time_in=_sa_utc(2024, 5, 1, 9, 0),
        time_out=_sa_utc(2024, 5, 1, 17, 0),
        reason_code="forgot_clock",
        shift_id=override.id,
    )
    r = client.post("/api/v1/attendance/adjustments", headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["adjustment"]["shift_id"] == str(override.id)
    adj_id = uuid.UUID(body["adjustment"]["id"])

    adj = db.get(Adjustment, adj_id)
    assert adj is not None
    assert adj.shift_id == override.id
    assert isinstance(adj.new_value, dict)
    assert adj.new_value.get("shift_name") == "Override-Day"
    assert adj.new_value.get("shift_id") == str(override.id)


def test_create_adjustment_unknown_shift_id_400_no_write(api, db):
    """Unknown shift_id -> 400 invalid_shift, no Adjustment row written."""
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_punch_day(db, "SO2")
    bogus = uuid.uuid4()

    before = db.scalar(select(Adjustment.id).where(Adjustment.employee_id == emp.id))

    payload = _adj_payload(
        emp.id, date(2024, 5, 1), "day_off",
        reason_code="system_correction",
        shift_id=bogus,
    )
    r = client.post("/api/v1/attendance/adjustments", headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "invalid_shift"
    assert err.get("context", {}).get("shift_id") == str(bogus) if err.get("context") else True

    db.expire_all()
    after = db.scalar(select(Adjustment.id).where(Adjustment.employee_id == emp.id))
    assert before == after


def test_recompute_uses_override_shift(api, db):
    """Override shift B (different length/rate) replaces detected shift A."""
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    day = date(2024, 5, 1)

    _mk_cal(db, day.year)
    shift_a = _mk_shift(db, name="Shift-A", start_hour=8, length_minutes=480, unpaid_break_minutes=60)
    _mk_rule(db, shift_a.id, value="1.0")
    emp = _mk_emp(db, "SO3", dflt_shift=shift_a.id)
    _mk_punch(db, emp.id, _sa_utc(2024, 5, 1, 8, 0))
    _mk_punch(db, emp.id, _sa_utc(2024, 5, 1, 17, 0))
    recompute_day(db, emp.id, day)

    shift_b = _mk_shift(db, name="Shift-B", start_hour=10, length_minutes=360, unpaid_break_minutes=0)
    _mk_rule(db, shift_b.id, value="1.0")

    payload = _adj_payload(
        emp.id, day, "worked",
        time_in=_sa_utc(2024, 5, 1, 10, 0),
        time_out=_sa_utc(2024, 5, 1, 16, 0),
        reason_code="system_correction",
        shift_id=shift_b.id,
    )
    r = client.post("/api/v1/attendance/adjustments", headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text

    db.expire_all()
    row = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == day,
    ))
    assert row is not None
    assert row.shift_id == shift_b.id, (
        f"expected override shift {shift_b.id}, got {row.shift_id}"
    )
    # Shift B: 360-minute scheduled length, 0 unpaid break, 10:00-16:00
    # = 360 raw minutes; grace 0, rounding 0.
    assert row.normal_minutes == 360
    assert row.overtime_minutes == 0
    assert row.worked_minutes == 360


def test_recompute_noop_does_not_bump_source_version(api, db):
    """Calling recompute_day with no intervening change must not bump source_version."""
    client, tenant = api
    emp, _ = _setup_punch_day(db, "SO4")
    day = date(2024, 5, 1)

    db.expire_all()
    before = db.scalar(select(AttendanceDay.source_version).where(
        AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == day,
    ))
    assert before is not None

    recompute_day(db, emp.id, day)

    db.expire_all()
    after = db.scalar(select(AttendanceDay.source_version).where(
        AttendanceDay.employee_id == emp.id, AttendanceDay.work_date == day,
    ))
    assert after == before, (
        f"source_version bumped on no-op recompute: {before} -> {after}"
    )


def test_history_returns_shift_id_and_name_after_shift_nulled(api, db):
    """After simulating FK ON DELETE SET NULL (shift_id -> None), history still
    returns shift_name from new_value.shift_name."""
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_punch_day(db, "SO5")
    override = _mk_shift(db, name="Override-History")
    _mk_rule(db, override.id)

    payload = _adj_payload(
        emp.id, date(2024, 5, 1), "worked",
        time_in=_sa_utc(2024, 5, 1, 8, 0),
        time_out=_sa_utc(2024, 5, 1, 17, 0),
        reason_code="forgot_clock",
        shift_id=override.id,
    )
    r = client.post("/api/v1/attendance/adjustments", headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text
    adj_id = uuid.UUID(r.json()["adjustment"]["id"])

    # Simulate FK ON DELETE SET NULL: null the shift_id in DB directly.
    # The shift row itself remains (so the FK is not violated), but the
    # adjustment's shift_id becomes None -- exactly the post-hard-delete state.
    adj = db.get(Adjustment, adj_id)
    adj.shift_id = None
    db.commit()

    r = client.get(
        f"/api/v1/attendance/adjustments/history?employee_id={emp.id}&work_date=2024-05-01",
        headers=_auth(tok, tenant.slug),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1, items
    row = items[0]
    assert row["shift_id"] is None
    assert row["shift_name"] == "Override-History", (
        f"expected shift_name from new_value.shift_name, got {row.get('shift_name')!r}"
    )


def test_history_newest_first_and_scope_enforced(api, db):
    """History returns rows newest-first, and out-of-scope callers get 404."""
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp, _ = _setup_punch_day(db, "SO6")
    override = _mk_shift(db, name="Override-Newest")
    _mk_rule(db, override.id)

    # First adjustment: day_off (no shift override).
    r1 = client.post(
        "/api/v1/attendance/adjustments",
        headers=_auth(tok, tenant.slug),
        json=_adj_payload(emp.id, date(2024, 5, 1), "day_off", reason_code="system_correction"),
    )
    assert r1.status_code == 201, r1.text
    first_id = r1.json()["adjustment"]["id"]

    # Second adjustment: worked with shift override.
    r2 = client.post(
        "/api/v1/attendance/adjustments",
        headers=_auth(tok, tenant.slug),
        json=_adj_payload(
            emp.id, date(2024, 5, 1), "worked",
            time_in=_sa_utc(2024, 5, 1, 8, 0),
            time_out=_sa_utc(2024, 5, 1, 17, 0),
            reason_code="forgot_clock",
            shift_id=override.id,
        ),
    )
    assert r2.status_code == 201, r2.text
    second_id = r2.json()["adjustment"]["id"]

    r = client.get(
        f"/api/v1/attendance/adjustments/history?employee_id={emp.id}&work_date=2024-05-01",
        headers=_auth(tok, tenant.slug),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2, items
    assert items[0]["id"] == second_id, "newest must be first"
    assert items[1]["id"] == first_id
    assert items[0]["shift_id"] == str(override.id)
    assert items[0]["shift_name"] == "Override-Newest"

    # Scope: an employee user (no scope over emp) gets 404, not 403.
    other_emp = _mk_emp(db, "SO6-OTHER")
    _mk_user(db, username="so6-emp", role="employee", password="So6EmpPass12345!", employee_id=other_emp.id)
    tok_out = _login(client, tenant.slug, "so6-emp", "So6EmpPass12345!")
    r = client.get(
        f"/api/v1/attendance/adjustments/history?employee_id={emp.id}&work_date=2024-05-01",
        headers=_auth(tok_out, tenant.slug),
    )
    assert r.status_code == 404, r.text

# END OF FILE
