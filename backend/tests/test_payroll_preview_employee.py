"""Chapter 4H B-3.1: single-employee preview endpoint tests."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.payroll_pay_periods import preview_employee
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.pay import PayPeriod, PayrollRun, Payslip, PayslipLine
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
    slug = f"prev1-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="Preview 1 Co",
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


def _mk_period(session) -> PayPeriod:
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"P-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        pay_date=date(2026, 1, 31),
        status="open",
        cutoff_at=datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc),
    )
    session.add(p)
    session.flush()
    return p


def _mk_run(session, period) -> PayrollRun:
    run = PayrollRun(
        id=uuid.uuid4(),
        pay_period_id=period.id,
        kind="preview",
        revision=1,
        status="completed",
        rules_snapshot={},
    )
    session.add(run)
    session.flush()
    return run


def _mk_payslip(session, run, period, emp) -> Payslip:
    ps = Payslip(
        id=uuid.uuid4(),
        payroll_run_id=run.id,
        pay_period_id=period.id,
        employee_id=emp.id,
        revision=1,
        status="preview",
        gross=Decimal("800.00"),
        pre_tax_deductions=Decimal("0"),
        taxable_income=Decimal("800.00"),
        paye=Decimal("60.00"),
        uif_employee=Decimal("8.00"),
        uif_employer=Decimal("8.00"),
        sdl=Decimal("8.00"),
        other_deductions=Decimal("0"),
        reimbursements=Decimal("0"),
        net=Decimal("732.00"),
        employer_costs={},
        snapshot={},
        calculation_context={
            "attendance_warnings": ["test-warn-1"],
        },
    )
    session.add(ps)
    session.flush()
    # Two earning lines and one deduction to prove line surfacing
    session.add(PayslipLine(
        id=uuid.uuid4(), payslip_id=ps.id,
        line_type="earning", step="gross", sort_order=0,
        label="Normal Hours (480 min)", amount=Decimal("800.00"),
        source_ref={
            "attendance_derived": True,
            "earning_type_code": "hourly_normal",
            "rate_source": "attendance",
            "minutes": 480,
            "amount": "800.00",
        },
    ))
    session.add(PayslipLine(
        id=uuid.uuid4(), payslip_id=ps.id,
        line_type="deduction", step="statutory", sort_order=300,
        label="UIF (employee)", amount=Decimal("8.00"),
        source_ref={"statutory": "uif", "amount": "8.00"},
    ))
    session.flush()
    return ps


def test_preview_employee_returns_single_row(session):
    admin = _admin(session)
    emp = _mk_employee(session)
    period = _mk_period(session)
    run = _mk_run(session, period)
    _mk_payslip(session, run, period, emp)
    session.commit()

    out = preview_employee(period.id, emp.id, session, admin)
    assert out.employee_id == emp.id
    assert out.employee_code == emp.employee_code
    assert out.gross == Decimal("800.00")
    assert out.net == Decimal("732.00")
    assert out.warnings == ["test-warn-1"]
    assert len(out.lines) == 1
    assert out.lines[0].earning_type_code == "hourly_normal"
    assert out.lines[0].minutes == 480
    assert out.lines[0].amount == Decimal("800.00")
    # UIF deduction surfaced
    uif = [d for d in out.deductions if d.deduction_type_name == "UIF (employee)"]
    assert len(uif) == 1
    assert uif[0].amount == Decimal("8.00")


def test_preview_employee_404_for_unknown_employee(session):
    admin = _admin(session)
    _mk_period(session)
    session.commit()
    period = session.scalar(select(PayPeriod))
    bogus = uuid.uuid4()
    with pytest.raises(AppError) as exc:
        preview_employee(period.id, bogus, session, admin)
    assert exc.value.code == "not_found"


def test_preview_employee_404_for_unknown_period(session):
    admin = _admin(session)
    emp = _mk_employee(session)
    session.commit()
    with pytest.raises(AppError) as exc:
        preview_employee(uuid.uuid4(), emp.id, session, admin)
    assert exc.value.code == "not_found"


def test_preview_employee_409_when_no_run(session):
    admin = _admin(session)
    emp = _mk_employee(session)
    period = _mk_period(session)
    session.commit()

    with pytest.raises(AppError) as exc:
        preview_employee(period.id, emp.id, session, admin)
    assert exc.value.code == "no_preview_run"


def test_preview_employee_matches_expected_shape(session):
    admin = _admin(session)
    emp = _mk_employee(session)
    period = _mk_period(session)
    run = _mk_run(session, period)
    _mk_payslip(session, run, period, emp)
    session.commit()

    out = preview_employee(period.id, emp.id, session, admin)
    assert out.pay_period_id == period.id
    assert out.revision == 1
    assert out.status == "completed"
    assert isinstance(out.lines, list)
    assert isinstance(out.deductions, list)
