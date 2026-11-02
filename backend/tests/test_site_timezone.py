"""B-5/B-11: site_timezone_map and DayOut.site_timezone propagation."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.attendance import _to_out as attendance_to_out
from app.db.tenant.models.attendance import AttendanceDay
from app.db.tenant.models.organisation import Branch, Company, Site
from app.db.tenant.models.people import Employee
from app.services.site_timezone import site_timezone_map


@pytest.fixture()
def session(tenant_engine_app):
    s = Session(bind=tenant_engine_app)
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _add_company(session: Session, tz: str = "Africa/Johannesburg") -> Company:
    c = Company(
        legal_name="Test Co",
        country_code="ZA",
        currency="ZAR",
        default_timezone=tz,
        settings={},
        row_version=1,
    )
    session.add(c)
    session.flush()
    return c


def _add_branch(session: Session) -> Branch:
    code = f"BR-{uuid.uuid4().hex[:8]}"
    b = Branch(name=f"Branch {code}", code=code, is_active=True, row_version=1)
    session.add(b)
    session.flush()
    return b


def _add_site(session: Session, branch_id, tz: str) -> Site:
    code = f"S-{uuid.uuid4().hex[:8]}"
    s = Site(
        branch_id=branch_id,
        name=f"Site {code}",
        code=code,
        site_type="site",
        timezone=tz,
        is_active=True,
        row_version=1,
    )
    session.add(s)
    session.flush()
    return s


def _add_employee(session: Session, site_id=None) -> Employee:
    code = f"E-{uuid.uuid4().hex[:8]}"
    e = Employee(
        employee_code=code,
        first_name="Test",
        last_name=code,
        hire_date=date(2020, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        site_id=site_id,
        row_version=1,
    )
    session.add(e)
    session.flush()
    return e


def _fake_day() -> AttendanceDay:
    return AttendanceDay(
        id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        work_date=date(2026, 1, 15),
        status="absent",
        first_in=None,
        last_out=None,
        worked_minutes=0,
        normal_minutes=0,
        overtime_minutes=0,
        raw_minutes=0,
        shift_id=None,
        flags=[],
        source_version=0,
        locked=False,
        row_version=1,
        computed_at=datetime.now(timezone.utc),
    )


def test_site_timezone_map_empty_input(session):
    assert site_timezone_map(session, []) == {}


def test_site_timezone_from_site(session):
    _add_company(session, "Africa/Johannesburg")
    b = _add_branch(session)
    site = _add_site(session, b.id, "Europe/London")
    e = _add_employee(session, site.id)

    m = site_timezone_map(session, [e.id])
    assert m[e.id] == "Europe/London"


def test_site_timezone_falls_back_to_company(session):
    _add_company(session, "Africa/Johannesburg")
    e = _add_employee(session, None)

    m = site_timezone_map(session, [e.id])
    assert m[e.id] == "Africa/Johannesburg"


def test_attendance_to_out_includes_site_timezone():
    out = attendance_to_out(_fake_day(), site_timezone="Africa/Johannesburg")
    assert out.site_timezone == "Africa/Johannesburg"


def test_attendance_to_out_none_site_timezone():
    out = attendance_to_out(_fake_day())
    assert out.site_timezone is None