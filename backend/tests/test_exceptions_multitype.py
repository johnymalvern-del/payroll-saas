"""Chapter 4H B-6: multi-value type filter on GET /attendance/exceptions."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.exceptions import _normalise_type_filter, list_exceptions
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.attendance import ExceptionItem
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.people import Employee, User
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    slug = f"b6-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="B6 Co",
        admin_username="admin",
        admin_password_hash=hash_password("AdminPassword123!"),
    )
    try:
        yield _DisposableTenant(
            slug=slug,
            tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
    finally:
        _drop_tenant_database(result.tenant_db_name)
        with control_session() as s:
            r = s.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if r is not None:
                s.delete(r)


@pytest.fixture()
def session(disposable_tenant) -> Iterator[Session]:
    url = (
        "postgresql+psycopg://payroll_app:payroll_app_dev_password"
        f"@localhost:5432/{disposable_tenant.tenant_db_name}"
    )
    engine = create_engine(url, future=True)
    s = Session(bind=engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        engine.dispose()


def _admin(session) -> User:
    admin = session.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    return admin


def _mk_company(session) -> Company:
    c = session.scalar(select(Company))
    if c is not None:
        return c
    c = Company(
        legal_name="B6 Co",
        country_code="ZA",
        currency="ZAR",
        default_timezone="Africa/Johannesburg",
        settings={},
        row_version=1,
    )
    session.add(c)
    session.flush()
    return c


def _mk_employee(session) -> Employee:
    emp = Employee(
        employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="Test",
        last_name="Emp",
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        base_rate=Decimal("100.00"),
        row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


def _mk_exc(session, emp, work_date, type_: str, status: str = "open") -> ExceptionItem:
    e = ExceptionItem(
        id=uuid.uuid4(),
        employee_id=emp.id,
        work_date=work_date,
        type=type_,
        source_ref={},
        suggested_fix={},
        status=status,
    )
    session.add(e)
    session.flush()
    return e


def _seed_exceptions(session):
    _mk_company(session)
    emp = _mk_employee(session)
    _mk_exc(session, emp, date(2026, 1, 5), "missing_out")
    _mk_exc(session, emp, date(2026, 1, 6), "missing_out")
    _mk_exc(session, emp, date(2026, 1, 7), "too_long")
    _mk_exc(session, emp, date(2026, 1, 8), "duplicate")
    _mk_exc(session, emp, date(2026, 1, 9), "employee_query")
    session.commit()


# ---------------------------------------------------------------------------
# _normalise_type_filter unit tests
# ---------------------------------------------------------------------------

def test_normalise_none_returns_none():
    assert _normalise_type_filter(None) is None


def test_normalise_empty_list_returns_none():
    assert _normalise_type_filter([]) is None


def test_normalise_single_value():
    assert _normalise_type_filter(["missing_out"]) == ["missing_out"]


def test_normalise_repeated_values():
    got = _normalise_type_filter(["missing_out", "too_long"])
    assert got == ["missing_out", "too_long"]


def test_normalise_comma_separated():
    got = _normalise_type_filter(["missing_out,too_long"])
    assert got == ["missing_out", "too_long"]


def test_normalise_mixed_repeated_and_comma():
    got = _normalise_type_filter(["missing_out,too_long", "duplicate"])
    assert got == ["duplicate", "missing_out", "too_long"]


def test_normalise_whitespace_stripped():
    got = _normalise_type_filter([" missing_out , too_long "])
    assert got == ["missing_out", "too_long"]


def test_normalise_all_empty_returns_none():
    assert _normalise_type_filter([""]) is None
    assert _normalise_type_filter([",,,"]) is None
    assert _normalise_type_filter(["", ","]) is None


def test_normalise_duplicates_deduped():
    got = _normalise_type_filter(["missing_out", "missing_out,missing_out"])
    assert got == ["missing_out"]


# ---------------------------------------------------------------------------
# Endpoint behaviour (list_exceptions called directly)
# ---------------------------------------------------------------------------

def test_filter_single_type_still_works(session):
    _seed_exceptions(session)
    admin = _admin(session)
    out = list_exceptions(
        db=session, user=admin,
        limit=100, cursor=None, include_total=False,
        employee_id=None, site_id=None, department_id=None,
        from_date=None, to_date=None,
        type_filter=["missing_out"], status_filter=None,
    )
    assert len(out.items) == 2
    assert all(i.type == "missing_out" for i in out.items)


def test_filter_two_types_repeated_param(session):
    _seed_exceptions(session)
    admin = _admin(session)
    out = list_exceptions(
        db=session, user=admin,
        limit=100, cursor=None, include_total=False,
        employee_id=None, site_id=None, department_id=None,
        from_date=None, to_date=None,
        type_filter=["missing_out", "too_long"], status_filter=None,
    )
    types = {i.type for i in out.items}
    assert types == {"missing_out", "too_long"}
    assert len(out.items) == 3


def test_filter_comma_separated(session):
    _seed_exceptions(session)
    admin = _admin(session)
    out = list_exceptions(
        db=session, user=admin,
        limit=100, cursor=None, include_total=False,
        employee_id=None, site_id=None, department_id=None,
        from_date=None, to_date=None,
        type_filter=["missing_out,too_long"], status_filter=None,
    )
    types = {i.type for i in out.items}
    assert types == {"missing_out", "too_long"}
    assert len(out.items) == 3


def test_filter_mixed_repeated_and_comma(session):
    _seed_exceptions(session)
    admin = _admin(session)
    out = list_exceptions(
        db=session, user=admin,
        limit=100, cursor=None, include_total=False,
        employee_id=None, site_id=None, department_id=None,
        from_date=None, to_date=None,
        type_filter=["missing_out,too_long", "duplicate"], status_filter=None,
    )
    types = {i.type for i in out.items}
    assert types == {"missing_out", "too_long", "duplicate"}
    assert len(out.items) == 4


def test_filter_unknown_type_ignored(session):
    """Unknown codes don't 400 — they simply match nothing (0 rows)."""
    _seed_exceptions(session)
    admin = _admin(session)
    out = list_exceptions(
        db=session, user=admin,
        limit=100, cursor=None, include_total=False,
        employee_id=None, site_id=None, department_id=None,
        from_date=None, to_date=None,
        type_filter=["totally_fake_code"], status_filter=None,
    )
    assert out.items == []


def test_filter_empty_type_no_filter(session):
    """`?type=` with empty value = no filter (all open rows)."""
    _seed_exceptions(session)
    admin = _admin(session)
    out = list_exceptions(
        db=session, user=admin,
        limit=100, cursor=None, include_total=False,
        employee_id=None, site_id=None, department_id=None,
        from_date=None, to_date=None,
        type_filter=[""], status_filter=None,
    )
    assert len(out.items) == 5


def test_filter_union_reflected_in_total(session):
    _seed_exceptions(session)
    admin = _admin(session)
    out = list_exceptions(
        db=session, user=admin,
        limit=100, cursor=None, include_total=True,
        employee_id=None, site_id=None, department_id=None,
        from_date=None, to_date=None,
        type_filter=["missing_out", "too_long"], status_filter=None,
    )
    assert out.total == 3
    assert len(out.items) == 3
