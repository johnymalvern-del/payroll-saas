"""Chapter 4H B-4e: demo PDF watermark tests."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.attendance import (
    AttendanceDay,
    AttendanceSegment,
)
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.pay import EarningType, PayPeriod
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee
from app.services.payroll_pdf import (
    _DEMO_MARK,
    _demo_flag_from_payslip,
    _payslip_text_lines,
    render_payslip_pdf,
)
from app.services.payroll_runner import _build_attendance_earnings
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
    slug = f"pdfdemo-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="PDF Demo Co",
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


class _FakePayslip:
    def __init__(self, *, ctx=None):
        self.revision = 1
        self.status = "current"
        self.gross = Decimal("1000.00")
        self.pre_tax_deductions = Decimal("0.00")
        self.taxable_income = Decimal("1000.00")
        self.paye = Decimal("100.00")
        self.uif_employee = Decimal("10.00")
        self.other_deductions = Decimal("0.00")
        self.reimbursements = Decimal("0.00")
        self.net = Decimal("890.00")
        self.uif_employer = Decimal("10.00")
        self.sdl = Decimal("10.00")
        self.calculation_context = ctx


class _FakeEmployee:
    def __init__(self):
        self.employee_code = "EMP-001"
        self.first_name = "Ada"
        self.last_name = "Mokoena"


class _FakePeriod:
    def __init__(self):
        self.period_key = "2026-01"
        self.pay_date = date(2026, 1, 31)


def test_render_payslip_pdf_without_demo_no_marker():
    payslip = _FakePayslip(ctx=None)
    pdf = render_payslip_pdf(payslip, _FakeEmployee(), _FakePeriod())
    assert pdf.startswith(b"%PDF-1.4")
    assert _DEMO_MARK.encode("latin-1") not in pdf


def test_render_payslip_pdf_with_explicit_demo_flag():
    payslip = _FakePayslip(ctx=None)
    pdf = render_payslip_pdf(
        payslip, _FakeEmployee(), _FakePeriod(), demo_values=True,
    )
    assert _DEMO_MARK.encode("latin-1") in pdf


def test_render_payslip_pdf_reads_demo_flag_from_context():
    payslip = _FakePayslip(ctx={
        "attendance_inputs": {
            "settings": {"demo_values": True},
        },
    })
    pdf = render_payslip_pdf(payslip, _FakeEmployee(), _FakePeriod())
    assert _DEMO_MARK.encode("latin-1") in pdf


def test_demo_flag_false_when_context_missing():
    payslip = _FakePayslip(ctx=None)
    assert _demo_flag_from_payslip(payslip) is False


def test_demo_flag_false_when_context_shallow():
    payslip = _FakePayslip(ctx={"attendance_inputs": {}})
    assert _demo_flag_from_payslip(payslip) is False


def test_payslip_text_lines_have_marker_when_demo():
    lines = _payslip_text_lines(
        _FakePayslip(), _FakeEmployee(), _FakePeriod(), demo_values=True,
    )
    assert lines[0] == _DEMO_MARK
    assert lines[-1] == _DEMO_MARK


def test_payslip_text_lines_no_marker_when_not_demo():
    lines = _payslip_text_lines(
        _FakePayslip(), _FakeEmployee(), _FakePeriod(), demo_values=False,
    )
    assert _DEMO_MARK not in lines


def _mk_settings(
    session,
    *,
    demo_values: bool,
    attendance_earning_map: dict | None = None,
) -> PayrollSettings:
    row = PayrollSettings(
        id=uuid.uuid4(),
        age_reference_date="date_of_birth",
        sdl_applies=True,
        net_pay_floor=Decimal("0.00"),
        formula_acks={},
        attendance_earning_map=attendance_earning_map or {},
        unpaid_day_behaviour=None,
        unpaid_day_formula_code=None,
        public_holiday_unworked_monthly=None,
        public_holiday_paid=None,
        leave_authoritative_source=None,
        monthly_hourly_derivation_formula_code=None,
        leave_earning_for_monthly=None,
        demo_values=demo_values,
        row_version=1,
    )
    session.add(row)
    session.flush()
    return row


def _mk_company(session):
    c = Company(
        legal_name="PDF Demo Co",
        country_code="ZA",
        currency="ZAR",
        default_timezone="Africa/Johannesburg",
        settings={},
        row_version=1,
    )
    session.add(c)
    session.flush()
    return c


def _mk_earning_type(session, *, code: str) -> EarningType:
    et = EarningType(
        id=uuid.uuid4(),
        name=code.replace("_", " ").title(),
        code=code,
        calc_method="per_hour",
        frequency="regular",
        is_taxable=True,
        counts_for_uif=True,
        counts_for_sdl=True,
        proration_rule="none",
        is_system=True,
        is_active=True,
        row_version=1,
    )
    session.add(et)
    session.flush()
    return et


def _mk_period(session):
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


def _mk_employee(session):
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


def test_runner_snapshot_includes_demo_values_true(session):
    _mk_company(session)
    _mk_earning_type(session, code="hourly_normal")
    _mk_settings(
        session,
        demo_values=True,
        attendance_earning_map={"normal|weekday|any": "hourly_normal"},
    )
    emp = _mk_employee(session)
    period = _mk_period(session)
    day = AttendanceDay(
        id=uuid.uuid4(),
        employee_id=emp.id,
        work_date=date(2026, 1, 5),
        status="present",
        first_in=None,
        last_out=None,
        worked_minutes=480,
        normal_minutes=480,
        overtime_minutes=0,
        raw_minutes=480,
        shift_id=None,
        flags=[],
        source_version=0,
        locked=False,
        row_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    session.add(day)
    session.flush()
    session.add(AttendanceSegment(
        id=uuid.uuid4(),
        attendance_day_id=day.id,
        local_date=day.work_date,
        day_type="weekday",
        kind="normal",
        tier=1,
        minutes=480,
        rate_method="multiplier",
        rate_value=Decimal("1.0"),
        overtime_status=None,
        source_refs=[],
    ))
    session.flush()

    _lines, _warnings, snap = _build_attendance_earnings(session, emp, period)
    assert snap["settings"]["demo_values"] is True


def test_runner_snapshot_includes_demo_values_false(session):
    _mk_company(session)
    _mk_settings(session, demo_values=False)
    emp = _mk_employee(session)
    period = _mk_period(session)
    session.flush()

    _lines, _warnings, snap = _build_attendance_earnings(session, emp, period)
    assert snap["settings"]["demo_values"] is False
