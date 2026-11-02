"""Chapter 4H B-4d: finalise open-exceptions ack + preview warning surfacing.

Uses the real provisioned admin `User` row for the acting user; a fabricated
`SimpleNamespace(id=uuid4(), ...)` violates the FK on
`payroll_run.started_by_user_id`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.payroll_pay_periods import _preview_row_from_payslip
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.attendance import ExceptionItem
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.pay import PayPeriod, Payslip
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, User
from app.services.payroll_formulas import FORMULA_REGISTRY
from app.services.payroll_runner import (
    _count_open_exceptions_in_period,
    finalise,
)
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
    slug = f"finalise-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="Finalise Ack Co",
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
    """Real admin User row (FK target for payroll_run.started_by_user_id)."""
    admin = session.scalar(select(User).where(User.username == "admin"))
    assert admin is not None, "provision_tenant did not create an admin user"
    return admin


def _mk_company(session) -> Company:
    c = Company(
        legal_name="Finalise Co",
        country_code="ZA",
        currency="ZAR",
        default_timezone="Africa/Johannesburg",
        settings={},
        row_version=1,
    )
    session.add(c)
    session.flush()
    return c


def _mk_settings_with_acks(session) -> PayrollSettings:
    row = PayrollSettings(
        id=uuid.uuid4(),
        age_reference_date="date_of_birth",
        sdl_applies=True,
        net_pay_floor=Decimal("0.00"),
        formula_acks={code: {"acknowledged_at": "x"} for code in FORMULA_REGISTRY},
        attendance_earning_map={},
        unpaid_day_behaviour=None,
        unpaid_day_formula_code=None,
        public_holiday_unworked_monthly=None,
        public_holiday_paid=None,
        leave_authoritative_source=None,
        monthly_hourly_derivation_formula_code=None,
        leave_earning_for_monthly=None,
        demo_values=False,
        row_version=1,
    )
    session.add(row)
    session.flush()
    return row


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


def _mk_open_exception(session, emp, work_date, type_="missing_out", status="open") -> ExceptionItem:
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


# ---------------------------------------------------------------------------
# _count_open_exceptions_in_period helper
# ---------------------------------------------------------------------------

def test_count_open_exceptions_zero_when_none(session):
    period = _mk_period(session)
    count, sample = _count_open_exceptions_in_period(session, period)
    assert count == 0
    assert sample == []


def test_count_open_exceptions_returns_count_and_sample(session):
    emp = _mk_employee(session)
    period = _mk_period(session)
    for i in range(7):
        _mk_open_exception(session, emp, date(2026, 1, 1 + i), "missing_out")

    count, sample = _count_open_exceptions_in_period(session, period)
    assert count == 7
    assert len(sample) == 5
    assert all("employee_id" in s and "work_date" in s and "type" in s for s in sample)


def test_count_open_exceptions_ignores_resolved_and_out_of_range(session):
    emp = _mk_employee(session)
    period = _mk_period(session)
    _mk_open_exception(session, emp, date(2026, 1, 5), "missing_out", status="resolved")
    _mk_open_exception(session, emp, date(2026, 2, 5), "missing_out")

    count, _ = _count_open_exceptions_in_period(session, period)
    assert count == 0


# ---------------------------------------------------------------------------
# finalise refusals
# ---------------------------------------------------------------------------

def test_finalise_refuses_open_exceptions_without_ack(session):
    _mk_company(session)
    _mk_settings_with_acks(session)
    emp = _mk_employee(session)
    period = _mk_period(session)
    _mk_open_exception(session, emp, date(2026, 1, 5), "missing_out")

    with pytest.raises(AppError) as exc:
        finalise(session, _admin(session), period)
    assert exc.value.code == "open_exceptions_in_period"
    assert (exc.value.details or {}).get("count", 0) >= 1


def test_finalise_refuses_open_exceptions_with_blank_ack(session):
    _mk_company(session)
    _mk_settings_with_acks(session)
    emp = _mk_employee(session)
    period = _mk_period(session)
    _mk_open_exception(session, emp, date(2026, 1, 5), "missing_out")

    with pytest.raises(AppError) as exc:
        finalise(session, _admin(session), period, ack_open_exceptions_reason="   ")
    assert exc.value.code == "open_exceptions_in_period"


def test_finalise_with_ack_passes_open_exceptions_check(session):
    """With ack, finalise passes the open-exceptions gate.

    The run then fails later (no statutory tables), but the code must NOT
    be open_exceptions_in_period — the ack cleared that gate.
    """
    _mk_company(session)
    _mk_settings_with_acks(session)
    emp = _mk_employee(session)
    period = _mk_period(session)
    _mk_open_exception(session, emp, date(2026, 1, 5), "missing_out")

    with pytest.raises(AppError) as exc:
        finalise(
            session, _admin(session), period,
            ack_open_exceptions_reason="Acknowledged: 1 open exception for review",
        )
    assert exc.value.code != "open_exceptions_in_period"


# ---------------------------------------------------------------------------
# Preview warning surfacing
# ---------------------------------------------------------------------------

def _mk_payslip(session, *, gross="1000.00", paye="100.00", net="890.00",
                ctx=None) -> Payslip:
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"PP-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        pay_date=date(2026, 1, 31),
        status="open",
        cutoff_at=datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc),
    )
    session.add(p)
    session.flush()

    from app.db.tenant.models.pay import PayrollRun
    run = PayrollRun(
        id=uuid.uuid4(),
        pay_period_id=p.id,
        kind="preview",
        revision=1,
        status="completed",
        rules_snapshot={},
    )
    session.add(run)
    session.flush()

    emp = _mk_employee(session)

    ps = Payslip(
        id=uuid.uuid4(),
        payroll_run_id=run.id,
        pay_period_id=p.id,
        employee_id=emp.id,
        revision=1,
        status="preview",
        gross=Decimal(gross),
        pre_tax_deductions=Decimal("0"),
        taxable_income=Decimal("0"),
        paye=Decimal(paye),
        uif_employee=Decimal("0"),
        uif_employer=Decimal("0"),
        sdl=Decimal("0"),
        other_deductions=Decimal("0"),
        reimbursements=Decimal("0"),
        net=Decimal(net),
        employer_costs={},
        snapshot={},
        calculation_context=ctx or {},
    )
    session.add(ps)
    session.flush()
    return ps


def test_preview_row_includes_attendance_warnings_from_context(session):
    payslip = _mk_payslip(session, ctx={
        "attendance_warnings": [
            "overtime_unapproved:E001:2026-01-05:60min",
            "rate_history_missing:E001:2026-01-06:using_current_base_rate",
        ],
    })
    emp = session.scalar(select(Employee).where(Employee.id == payslip.employee_id))
    row = _preview_row_from_payslip(payslip, emp)
    assert row.warnings == [
        "overtime_unapproved:E001:2026-01-05:60min",
        "rate_history_missing:E001:2026-01-06:using_current_base_rate",
    ]


def test_preview_row_empty_warnings_when_context_missing(session):
    payslip = _mk_payslip(session, ctx={})
    emp = session.scalar(select(Employee).where(Employee.id == payslip.employee_id))
    row = _preview_row_from_payslip(payslip, emp)
    assert row.warnings == []


def test_preview_row_empty_warnings_when_context_none(session):
    payslip = _mk_payslip(session, ctx=None)
    emp = session.scalar(select(Employee).where(Employee.id == payslip.employee_id))
    row = _preview_row_from_payslip(payslip, emp)
    assert row.warnings == []
