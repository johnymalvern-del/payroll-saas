"""Leave and requests model tests (Chapter 3, 3A).

Fresh tenants are provisioned via pytest; provision_tenant runs upgrade head
on each, so migration 0016 is applied on every run of this file.

Covers: table existence, unique + check constraints, ledger append-only via
both the grant (payroll_app) and the trigger (superuser path).
"""
from __future__ import annotations
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.tenant.models.leave import (
    LeaveBalance, LeaveBalanceLedger, LeaveRequest, LeaveType,
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
    from app.services.provisioning import (
        _drop_tenant_database, _tenant_db_name, provision_tenant,
    )
    slug = f"lv-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Leave Test",
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
def tenant(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    session = Session(engine)
    try:
        yield session, engine, disposable_tenant.tenant_db_name
    finally:
        session.close()


def _mk_leave_type(session, *, code="annual"):
    lt = LeaveType(
        name=f"LT-{code}", code=code, unit="day",
        accrual_method="annual_upfront",
        accrual_amount=Decimal("15.0"),
    )
    session.add(lt); session.commit()
    return lt


def _mk_employee(session, *, code="E-LV"):
    emp = Employee(
        employee_code=code, first_name="A", last_name=code,
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
    )
    session.add(emp); session.commit()
    return emp


def test_all_leave_tables_present(tenant):
    _, engine, _ = tenant
    expected = {
        "leave_type", "leave_balance", "leave_balance_ledger",
        "leave_request", "leave_request_day", "leave_approval_step",
        "leave_attachment", "advance_request", "grievance",
    }
    with engine.connect() as conn:
        found = {r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public'"
        ))}
    assert expected <= found, f"missing: {sorted(expected - found)}"


def test_leave_type_code_unique(tenant):
    session, _, _ = tenant
    _mk_leave_type(session, code="dup")
    session.add(LeaveType(name="Other", code="dup", unit="day",
                          accrual_method="annual_upfront"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_leave_balance_scope_unique(tenant):
    session, _, _ = tenant
    emp = _mk_employee(session)
    lt = _mk_leave_type(session)
    session.add(LeaveBalance(
        employee_id=emp.id, leave_type_id=lt.id,
        cycle_start=date(2024, 1, 1), cycle_end=date(2024, 12, 31),
    ))
    session.commit()
    session.add(LeaveBalance(
        employee_id=emp.id, leave_type_id=lt.id,
        cycle_start=date(2024, 1, 1), cycle_end=date(2024, 12, 31),
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_leave_request_rejects_inverted_dates(tenant):
    session, _, _ = tenant
    emp = _mk_employee(session)
    lt = _mk_leave_type(session)
    session.add(LeaveRequest(
        employee_id=emp.id, leave_type_id=lt.id,
        from_date=date(2024, 5, 10), to_date=date(2024, 5, 1),
        days_requested=Decimal("1"),
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_leave_request_rejects_zero_days(tenant):
    session, _, _ = tenant
    emp = _mk_employee(session)
    lt = _mk_leave_type(session)
    session.add(LeaveRequest(
        employee_id=emp.id, leave_type_id=lt.id,
        from_date=date(2024, 5, 1), to_date=date(2024, 5, 1),
        days_requested=Decimal("0"),
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_ledger_app_can_insert_and_select(tenant):
    session, _, _ = tenant
    emp = _mk_employee(session)
    lt = _mk_leave_type(session)
    ledger = LeaveBalanceLedger(
        employee_id=emp.id, leave_type_id=lt.id,
        delta=Decimal("1.5"), reason="accrual",
    )
    session.add(ledger); session.commit()
    count = session.execute(text(
        "SELECT COUNT(*) FROM leave_balance_ledger WHERE id = :id"
    ), {"id": str(ledger.id)}).scalar()
    assert count == 1


def test_ledger_app_cannot_update(tenant):
    session, _, _ = tenant
    emp = _mk_employee(session)
    lt = _mk_leave_type(session)
    ledger = LeaveBalanceLedger(
        employee_id=emp.id, leave_type_id=lt.id,
        delta=Decimal("1.0"), reason="accrual",
    )
    session.add(ledger); session.commit()
    with pytest.raises(DBAPIError):
        session.execute(text(
            "UPDATE leave_balance_ledger SET delta = 99 WHERE id = :id"
        ), {"id": str(ledger.id)})
        session.commit()
    session.rollback()


def test_ledger_app_cannot_delete(tenant):
    session, _, _ = tenant
    emp = _mk_employee(session)
    lt = _mk_leave_type(session)
    ledger = LeaveBalanceLedger(
        employee_id=emp.id, leave_type_id=lt.id,
        delta=Decimal("1.0"), reason="accrual",
    )
    session.add(ledger); session.commit()
    with pytest.raises(DBAPIError):
        session.execute(text(
            "DELETE FROM leave_balance_ledger WHERE id = :id"
        ), {"id": str(ledger.id)})
        session.commit()
    session.rollback()


def test_ledger_trigger_blocks_update_as_superuser(tenant, disposable_tenant):
    session, _, _ = tenant
    emp = _mk_employee(session)
    lt = _mk_leave_type(session)
    ledger = LeaveBalanceLedger(
        employee_id=emp.id, leave_type_id=lt.id,
        delta=Decimal("1.0"), reason="accrual",
    )
    session.add(ledger); session.commit()
    ledger_id = ledger.id
    session.close()

    from app.services.provisioning import _admin_url
    admin_engine = create_engine(
        _admin_url(disposable_tenant.tenant_db_name), future=True,
    )
    try:
        with admin_engine.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text(
                    "UPDATE leave_balance_ledger SET delta = 99 WHERE id = :id"
                ), {"id": str(ledger_id)})
                conn.commit()
    finally:
        admin_engine.dispose()

# END OF FILE
