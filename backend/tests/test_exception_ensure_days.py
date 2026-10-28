"""Ensure-days creates absent_expected exceptions (C4 via ensure_days path)."""
from __future__ import annotations
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.attendance_engine import ensure_days
from app.core.security import hash_password
from app.db.tenant.models.attendance import (
    AttendanceDay, CountryCalendar, ExceptionItem,
)
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine


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
    slug = f"ed-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(slug=slug, name="ED Test", admin_username="admin", admin_password_hash=hash_password("TestPassword123!"))
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


def _mk_emp(session, code, *, hire=date(2024, 1, 1)):
    e = Employee(employee_code=code, first_name="A", last_name=code, hire_date=hire, status="active", employee_type="hourly", pay_basis="hourly", pay_frequency="monthly", row_version=1)
    session.add(e)
    session.commit()
    return e


def _mk_cal(session, year):
    session.add(CountryCalendar(country_code="ZA", holiday_date=date(year, 12, 25), name="Xmas", source_ref="test"))
    session.commit()


def test_ensure_days_absent_creates_exception(db):
    """Past weekday, default Mon-Fri pattern, no punches, no holiday ->
    absent day created by ensure_days AND absent_expected exception created."""
    _mk_cal(db, 2024)
    e = _mk_emp(db, "E1", hire=date(2024, 1, 1))
    ensure_days(db, [e.id], date(2024, 5, 7), date(2024, 5, 7), absent_grace_days=1)
    db.expire_all()
    day = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == e.id,
        AttendanceDay.work_date == date(2024, 5, 7),
    ))
    assert day is not None, "ensure_days should have created the day"
    assert day.status == "absent"
    exc = db.scalar(select(ExceptionItem).where(
        ExceptionItem.employee_id == e.id,
        ExceptionItem.work_date == date(2024, 5, 7),
        ExceptionItem.type == "absent_expected",
        ExceptionItem.status == "open",
    ))
    assert exc is not None, "absent day should have created absent_expected exception"

# END OF FILE
