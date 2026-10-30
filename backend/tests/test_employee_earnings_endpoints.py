"""Employee earnings/deductions model + behaviour (Chapter 4, Bundle 003c)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.tenant.models.pay import DeductionType, EarningType, EmployeeDeduction, EmployeeEarning
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
    from app.services.provisioning import (
        _drop_tenant_database, _tenant_db_name, provision_tenant,
    )
    slug = f"pemp-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Pay Emp Test",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(
            slug=result.slug, tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
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
def session_and_engine(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    session = Session(engine)
    try:
        yield session, engine
    finally:
        session.close()
        engine.dispose()


def _mk_employee(session, code="E-PAY-001"):
    emp = Employee(
        employee_code=code, first_name="A", last_name=code,
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
    )
    session.add(emp)
    session.commit()
    return emp


def _mk_earning_type(session, code="basic_salary"):
    et = EarningType(
        id=uuid.uuid4(), name="Basic", code=code,
        calc_method="fixed_amount", frequency="regular",
        is_system=False, is_active=True,
    )
    session.add(et)
    session.commit()
    return et


def _mk_deduction_type(session, code="retirement"):
    dt = DeductionType(
        id=uuid.uuid4(), name="Retirement", code=code,
        category="retirement", priority=10, is_pre_tax=True,
        is_system=False, is_active=True,
    )
    session.add(dt)
    session.commit()
    return dt


def test_tables_present(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    try:
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(sa.text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            assert "employee_earning" in tables
            assert "employee_deduction" in tables
    finally:
        engine.dispose()


def test_employee_earning_roundtrip(session_and_engine):
    session, _ = session_and_engine
    emp = _mk_employee(session)
    et = _mk_earning_type(session)
    row = EmployeeEarning(
        id=uuid.uuid4(), employee_id=emp.id, earning_type_id=et.id,
        amount=Decimal("15000.00"), rate=None,
        effective_from=date(2025, 1, 1), effective_to=None, is_active=True,
    )
    session.add(row)
    session.commit()
    fetched = session.query(EmployeeEarning).filter_by(employee_id=emp.id).one()
    assert fetched.amount == Decimal("15000.00")
    assert fetched.rate is None
    assert fetched.is_active is True


def test_employee_earning_rejects_both_null(session_and_engine):
    session, _ = session_and_engine
    emp = _mk_employee(session)
    et = _mk_earning_type(session)
    session.add(EmployeeEarning(
        id=uuid.uuid4(), employee_id=emp.id, earning_type_id=et.id,
        amount=None, rate=None,
        effective_from=date(2025, 1, 1), is_active=True,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_employee_deduction_roundtrip(session_and_engine):
    session, _ = session_and_engine
    emp = _mk_employee(session)
    dt = _mk_deduction_type(session)
    row = EmployeeDeduction(
        id=uuid.uuid4(), employee_id=emp.id, deduction_type_id=dt.id,
        amount=Decimal("500.00"), balance=Decimal("0.00"),
        effective_from=date(2025, 1, 1), is_active=True,
    )
    session.add(row)
    session.commit()
    fetched = session.query(EmployeeDeduction).filter_by(employee_id=emp.id).one()
    assert fetched.amount == Decimal("500.00")
    assert fetched.balance == Decimal("0.00")

# END OF FILE
