"""Chapter 4H B-4d.2: end-to-end demo preview + non-demo fail-closed.

Two scenarios, each on its own disposable tenant:
  1. Demo tenant (demo_values=True, full settings) — full run_preview through
     build_pipeline_config + _build_attendance_earnings + run_pipeline; the
     resulting Payslip carries demo_values in its attendance snapshot and its
     rendered PDF carries the DEMO marker.
  2. Non-demo tenant with unpaid_day_behaviour=None and an absent day —
     run_preview refuses with 409 unpaid_day_behaviour_not_configured, not
     silently produces a payslip.

Statutory tables are patched at the module boundary
(`payroll_runner._load_control_table` and `T.load_tax_tables`) with fake
fixtures — the control DB is untouched. Round-1 §5 remains respected: no
real statutory values are invented; the fake tables only exist to exercise
the pipeline, and the test asserts refusal / success, not exact tax amounts.
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

from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.attendance import (
    AttendanceDay,
    AttendanceSegment,
    Shift,
)
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.pay import PayPeriod, Payslip
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, User
from app.services import payroll_tax as T
from app.services.payroll_formulas import FORMULA_REGISTRY
from app.services.payroll_pdf import _DEMO_MARK, render_payslip_pdf
from app.services.payroll_runner import run_preview
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


_FAKE_UIF = [
    {"row_key": "employee_rate", "value": "0.01"},
    {"row_key": "employer_rate", "value": "0.01"},
    {"row_key": "monthly_ceiling", "value": "100000"},
]
_FAKE_SDL = [
    {"row_key": "rate", "value": "0.01"},
    {"row_key": "exemption_threshold_annual", "value": "50000"},
]
_FAKE_RETIREMENT = [
    {"row_key": "percentage_of_taxable_income", "value": "0.10"},
    {"row_key": "annual_cap", "value": "1000"},
]
_FAKE_BY_TYPE = {
    "uif": _FAKE_UIF,
    "sdl": _FAKE_SDL,
    "retirement_limit": _FAKE_RETIREMENT,
}


def _fake_load_control_table(table_type: str, on_date: date) -> list[dict]:
    return _FAKE_BY_TYPE[table_type]


def _fake_load_tax_tables(engine_or_session, on_date, country_code="ZA") -> T.TaxTables:
    return T.TaxTables(
        brackets=[
            {"row_key": "1", "lower_bound": "0", "upper_bound": "10000",
             "rate": "0.18", "base_tax": "0"},
        ],
        rebates={"primary": Decimal("1000"), "secondary_65": Decimal("0"),
                 "tertiary_75": Decimal("0")},
        thresholds={"below_age_65": Decimal("5000"),
                    "age_65_to_74": Decimal("5000"),
                    "age_75_plus": Decimal("5000")},
        medical_credits={"first_member": Decimal("0"),
                         "additional_member": Decimal("0"),
                         "first_dependant": Decimal("0")},
        retirement_limit={"percentage_of_taxable_income": Decimal("0.10"),
                          "annual_cap": Decimal("100000")},
        source_version="test",
    )


def _patch_statutory(monkeypatch):
    monkeypatch.setattr(
        "app.services.payroll_runner._load_control_table",
        _fake_load_control_table,
    )
    monkeypatch.setattr(T, "load_tax_tables", _fake_load_tax_tables)


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    slug = f"b4e2e-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="B4 E2E Co",
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
    """Provision inserted a company row; return it, don't duplicate."""
    company = session.scalar(select(Company))
    if company is None:
        c = Company(
            legal_name="B4 E2E Co",
            country_code="ZA",
            currency="ZAR",
            default_timezone="Africa/Johannesburg",
            settings={},
            row_version=1,
        )
        session.add(c)
        session.flush()
        return c
    return company


def _mk_settings_full(
    session,
    *,
    demo_values: bool,
    unpaid_day_behaviour: str | None,
) -> PayrollSettings:
    row = PayrollSettings(
        id=uuid.uuid4(),
        age_reference_date="date_of_birth",
        sdl_applies=True,
        net_pay_floor=Decimal("0.00"),
        formula_acks={code: {"acknowledged_at": "x"} for code in FORMULA_REGISTRY},
        attendance_earning_map={"normal|weekday|any": "hourly_normal"},
        unpaid_day_behaviour=unpaid_day_behaviour,
        unpaid_day_formula_code="gen_unpaid_absence",
        public_holiday_unworked_monthly=None,
        public_holiday_paid=None,
        leave_authoritative_source="adjustment",
        monthly_hourly_derivation_formula_code=None,
        leave_earning_for_monthly=False,
        demo_values=demo_values,
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
        date_of_birth=date(1990, 1, 1),
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        base_rate=Decimal("100.00"),
        overtime_eligible=False,
        clocks=True,
        row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


def _mk_shift(session) -> Shift:
    from datetime import datetime as _dt
    s = Shift(
        name=f"S-{uuid.uuid4().hex[:6]}",
        start_time=_dt.strptime("08:00", "%H:%M").time(),
        length_minutes=480,
        unpaid_break_minutes=0,
        paid_break_minutes=0,
        grace_late_minutes=0,
        grace_early_minutes=0,
        rounding_minutes=0,
        rounding_mode="nearest",
        min_overtime_minutes=0,
        overtime_requires_approval=False,
        max_shift_minutes=600,
        match_tolerance_minutes=60,
        salaried_premium_mode="full",
        grace_mode="threshold",
        pay_early_arrival=False,
        is_active=True,
        row_version=1,
    )
    session.add(s)
    session.flush()
    return s


def _mk_day(session, emp, work_date, *, status="present", shift_id=None) -> AttendanceDay:
    d = AttendanceDay(
        id=uuid.uuid4(),
        employee_id=emp.id,
        work_date=work_date,
        status=status,
        shift_id=shift_id,
        worked_minutes=480 if status == "present" else 0,
        normal_minutes=480 if status == "present" else 0,
        overtime_minutes=0,
        raw_minutes=480 if status == "present" else 0,
        flags=[],
        source_version=0,
        locked=False,
        row_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    session.add(d)
    session.flush()
    return d


def _mk_seg(session, day, *, minutes=480) -> AttendanceSegment:
    s = AttendanceSegment(
        id=uuid.uuid4(),
        attendance_day_id=day.id,
        local_date=day.work_date,
        day_type="weekday",
        kind="normal",
        tier=1,
        minutes=minutes,
        rate_method="multiplier",
        rate_value=Decimal("1.0"),
        overtime_status=None,
        source_refs=[],
    )
    session.add(s)
    session.flush()
    return s


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


def test_demo_tenant_preview_end_to_end_pdf_watermark(session, monkeypatch):
    """Demo tenant, one employee, one worked weekday.

    Proves the full pipeline from attendance_day+segment through
    run_preview to a persisted Payslip and rendered PDF; the payslip's
    attendance snapshot carries demo_values=True and the PDF carries the
    DEMO watermark.
    """
    _patch_statutory(monkeypatch)
    _mk_company(session)
    _mk_settings_full(session, demo_values=True, unpaid_day_behaviour="deduct_daily")
    emp = _mk_employee(session)
    shift = _mk_shift(session)
    day = _mk_day(session, emp, date(2026, 1, 5), shift_id=shift.id)
    _mk_seg(session, day, minutes=480)
    period = _mk_period(session)
    admin = _admin(session)

    run = run_preview(session, admin, period)
    session.commit()

    assert run.status == "completed"

    payslips = session.scalars(
        select(Payslip).where(Payslip.payroll_run_id == run.id)
    ).all()
    assert len(payslips) == 1
    ps = payslips[0]
    # Gross comes from 480 normal minutes * 100.00/hour * 1.0 multiplier
    assert ps.gross == Decimal("800.00")

    ctx = ps.calculation_context or {}
    snap = ctx.get("attendance_inputs") or {}
    settings_snap = snap.get("settings") or {}
    assert settings_snap.get("demo_values") is True
    assert snap.get("grouped_minutes", {}).get("normal|weekday|any") == 480

    pdf = render_payslip_pdf(ps, emp, period)
    assert pdf.startswith(b"%PDF-1.4")
    assert _DEMO_MARK.encode("latin-1") in pdf


def test_non_demo_unset_unpaid_day_behaviour_refuses_409(session, monkeypatch):
    """Non-demo tenant, absent day, unpaid_day_behaviour=None.

    The runner must refuse rather than silently produce a payslip with an
    unhandled absent day. 409 unpaid_day_behaviour_not_configured.
    """
    _patch_statutory(monkeypatch)
    _mk_company(session)
    _mk_settings_full(
        session, demo_values=False, unpaid_day_behaviour=None,
    )
    emp = _mk_employee(session)
    _mk_day(session, emp, date(2026, 1, 5), status="absent")
    period = _mk_period(session)
    admin = _admin(session)

    with pytest.raises(AppError) as exc:
        run_preview(session, admin, period)
    assert exc.value.code == "unpaid_day_behaviour_not_configured"
