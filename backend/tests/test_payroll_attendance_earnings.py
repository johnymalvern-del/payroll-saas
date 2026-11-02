"""Chapter 4H B-4c: attendance-to-earnings integration tests.

Covers `_build_attendance_earnings` and its end-to-end wiring through
`run_pipeline`. Locked days are INCLUDED (round-2 §1); missing mapping
keys 409 (round-2 §2); unpaid-day amounts are NEGATIVE earnings
(round-2 §3); monthly derivation formula required (round-2 §4); rate
in force uses `EmployeePayHistory` (round-2 §5); unapproved overtime
skipped with warning (round-2 §6); Decimal rounding per segment
(round-2 §7); leave source restricted to 'adjustment' (round-2 §9);
attendance snapshot stored on `calculation_context` (round-2 §10).
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
    ShiftRateRule,
)
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.pay import EarningType, PayPeriod
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, EmployeePayHistory
from app.services import payroll_pipeline as P
from app.services import payroll_tax as T
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
    slug = f"attearn-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Att Earnings Co",
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


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _mk_company(session) -> Company:
    c = Company(
        legal_name="Att Earnings Co",
        country_code="ZA",
        currency="ZAR",
        default_timezone="Africa/Johannesburg",
        settings={},
        row_version=1,
    )
    session.add(c)
    session.flush()
    return c


def _mk_settings(session, **overrides) -> PayrollSettings:
    defaults = dict(
        id=uuid.uuid4(),
        age_reference_date="date_of_birth",
        sdl_applies=True,
        net_pay_floor=Decimal("0.00"),
        formula_acks={},
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
    defaults.update(overrides)
    row = PayrollSettings(**defaults)
    session.add(row)
    session.flush()
    return row


def _mk_employee(session, *, pay_basis="hourly", base_rate="100.00",
                 contracted_weekly_hours=None, default_shift_id=None) -> Employee:
    emp = Employee(
        employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="Test",
        last_name="Emp",
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis=pay_basis,
        pay_frequency="monthly",
        base_rate=Decimal(base_rate) if base_rate else None,
        contracted_weekly_hours=contracted_weekly_hours,
        default_shift_id=default_shift_id,
        row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


def _mk_shift(session, *, length_minutes=480, overtime_requires_approval=True) -> Shift:
    s = Shift(
        name=f"S-{uuid.uuid4().hex[:6]}",
        start_time=time_8,
        length_minutes=length_minutes,
        unpaid_break_minutes=0,
        paid_break_minutes=0,
        grace_late_minutes=0,
        grace_early_minutes=0,
        rounding_minutes=0,
        rounding_mode="nearest",
        min_overtime_minutes=0,
        overtime_requires_approval=overtime_requires_approval,
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


def _mk_earning_type(session, *, code="hourly_normal", is_system=True) -> EarningType:
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
        is_system=is_system,
        is_active=True,
        row_version=1,
    )
    session.add(et)
    session.flush()
    return et


def _mk_day(session, emp, work_date, *, status="present", shift_id=None,
            locked=False, worked_minutes=0) -> AttendanceDay:
    d = AttendanceDay(
        id=uuid.uuid4(),
        employee_id=emp.id,
        work_date=work_date,
        status=status,
        shift_id=shift_id,
        worked_minutes=worked_minutes,
        normal_minutes=0,
        overtime_minutes=0,
        raw_minutes=0,
        flags=[],
        source_version=0,
        locked=locked,
        row_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    session.add(d)
    session.flush()
    return d


def _mk_seg(session, day, *, kind="normal", day_type="weekday", tier=1,
            minutes=480, rate_method="multiplier", rate_value="1.0",
            overtime_status=None) -> AttendanceSegment:
    s = AttendanceSegment(
        id=uuid.uuid4(),
        attendance_day_id=day.id,
        local_date=day.work_date,
        day_type=day_type,
        kind=kind,
        tier=tier,
        minutes=minutes,
        rate_method=rate_method,
        rate_value=Decimal(rate_value),
        overtime_status=overtime_status,
        source_refs=[],
    )
    session.add(s)
    session.flush()
    return s


def _mk_period(session, start=None, end=None) -> PayPeriod:
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"P-{uuid.uuid4().hex[:6]}",
        start_date=start or date(2026, 1, 1),
        end_date=end or date(2026, 1, 31),
        pay_date=(end or date(2026, 1, 31)),
        status="open",
        cutoff_at=datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc),
    )
    session.add(p)
    session.flush()
    return p


time_8 = datetime.strptime("08:00", "%H:%M").time()


# ---------------------------------------------------------------------------
# Mapping gate (round-2 §2)
# ---------------------------------------------------------------------------

def test_attendance_earnings_mapping_missing_409(session):
    _mk_company(session)
    _mk_settings(session, attendance_earning_map={})
    emp = _mk_employee(session)
    period = _mk_period(session)
    day = _mk_day(session, emp, date(2026, 1, 5))
    _mk_seg(session, day, kind="normal", day_type="weekday", minutes=480)

    with pytest.raises(AppError) as exc:
        _build_attendance_earnings(session, emp, period)
    assert exc.value.code == "attendance_earning_map_incomplete"
    assert "normal|weekday|any" in (exc.value.details or {}).get("missing_keys", [])


# ---------------------------------------------------------------------------
# Locked day included (round-2 §1)
# ---------------------------------------------------------------------------

def test_attendance_earnings_locked_day_still_included(session):
    _mk_company(session)
    _mk_earning_type(session, code="hourly_normal")
    _mk_settings(
        session,
        attendance_earning_map={"normal|weekday|any": "hourly_normal"},
    )
    emp = _mk_employee(session)
    period = _mk_period(session)
    day = _mk_day(session, emp, date(2026, 1, 5), locked=True)
    _mk_seg(session, day, kind="normal", day_type="weekday", minutes=480)

    lines, warnings, _snap = _build_attendance_earnings(session, emp, period)
    assert len(lines) == 1
    assert lines[0].amount == Decimal("800.00")


# ---------------------------------------------------------------------------
# Kind / day_type mapping
# ---------------------------------------------------------------------------

def test_attendance_earnings_hourly_saturday_uses_saturday_type(session):
    _mk_company(session)
    _mk_earning_type(session, code="hourly_saturday")
    _mk_settings(
        session,
        attendance_earning_map={"normal|saturday|any": "hourly_saturday"},
    )
    emp = _mk_employee(session)
    period = _mk_period(session)
    day = _mk_day(session, emp, date(2026, 1, 10))
    _mk_seg(session, day, kind="normal", day_type="saturday", minutes=480,
            rate_value="1.5")

    lines, _, _ = _build_attendance_earnings(session, emp, period)
    assert len(lines) == 1
    assert lines[0].amount == Decimal("1200.00")
    assert "hourly_saturday" in (lines[0].source_ref or {}).get("earning_type_code", "")


def test_attendance_earnings_hourly_sunday_uses_sunday_type(session):
    _mk_company(session)
    _mk_earning_type(session, code="hourly_sunday")
    _mk_settings(
        session,
        attendance_earning_map={"normal|sunday|any": "hourly_sunday"},
    )
    emp = _mk_employee(session)
    period = _mk_period(session)
    day = _mk_day(session, emp, date(2026, 1, 11))
    _mk_seg(session, day, kind="normal", day_type="sunday", minutes=480,
            rate_value="2.0")

    lines, _, _ = _build_attendance_earnings(session, emp, period)
    assert len(lines) == 1
    assert lines[0].amount == Decimal("1600.00")


def test_attendance_earnings_hourly_ph_uses_ph_type(session):
    _mk_company(session)
    _mk_earning_type(session, code="hourly_public_holiday")
    _mk_settings(
        session,
        attendance_earning_map={"normal|public_holiday|any": "hourly_public_holiday"},
    )
    emp = _mk_employee(session)
    period = _mk_period(session)
    day = _mk_day(session, emp, date(2026, 1, 1))
    _mk_seg(session, day, kind="normal", day_type="public_holiday",
            minutes=480, rate_value="2.0")

    lines, _, _ = _build_attendance_earnings(session, emp, period)
    assert len(lines) == 1
    assert lines[0].amount == Decimal("1600.00")


# ---------------------------------------------------------------------------
# Monthly normal segments covered by BASE_MONTHLY (skipped)
# ---------------------------------------------------------------------------

def test_attendance_earnings_monthly_normal_skipped(session):
    _mk_company(session)
    _mk_earning_type(session, code="hourly_normal")
    _mk_settings(
        session,
        attendance_earning_map={"normal|weekday|any": "hourly_normal"},
    )
    emp = _mk_employee(session, pay_basis="monthly", base_rate=None,
                       contracted_weekly_hours=40.0)
    period = _mk_period(session)
    day = _mk_day(session, emp, date(2026, 1, 5))
    _mk_seg(session, day, kind="normal", day_type="weekday", minutes=480)

    lines, _, _ = _build_attendance_earnings(session, emp, period)
    assert lines == []


# ---------------------------------------------------------------------------
# Monthly derivation formula required for OT (round-2 §4)
# ---------------------------------------------------------------------------

def test_attendance_earnings_monthly_overtime_derivation_unset_409(session):
    _mk_company(session)
    _mk_earning_type(session, code="overtime_t1")
    _mk_settings(
        session,
        attendance_earning_map={"overtime|weekday|1": "overtime_t1"},
        monthly_hourly_derivation_formula_code=None,
    )
    emp = _mk_employee(session, pay_basis="monthly", base_rate=None,
                       contracted_weekly_hours=40.0)
    period = _mk_period(session)
    shift = _mk_shift(session, overtime_requires_approval=False)
    day = _mk_day(session, emp, date(2026, 1, 5), shift_id=shift.id)
    _mk_seg(session, day, kind="overtime", day_type="weekday", tier=1,
            minutes=60, overtime_status="approved")

    with pytest.raises(AppError) as exc:
        _build_attendance_earnings(session, emp, period)
    assert exc.value.code == "monthly_hourly_derivation_not_configured"


def test_attendance_earnings_monthly_overtime_derivation_set_produces_line(session):
    _mk_company(session)
    _mk_earning_type(session, code="overtime_t1")
    _mk_earning_type(session, code="BASE_MONTHLY")
    _mk_settings(
        session,
        attendance_earning_map={"overtime|weekday|1": "overtime_t1"},
        monthly_hourly_derivation_formula_code="hourly_rate_from_monthly",
    )
    emp = _mk_employee(session, pay_basis="monthly", base_rate=None,
                       contracted_weekly_hours=40.0)
    from app.db.tenant.models.pay import EmployeeEarning
    base_et = session.scalar(select(EarningType).where(EarningType.code == "BASE_MONTHLY"))
    session.add(EmployeeEarning(
        id=uuid.uuid4(),
        employee_id=emp.id,
        earning_type_id=base_et.id,
        amount=Decimal("25000.00"),
        effective_from=date(2024, 1, 1),
        is_active=True,
        row_version=1,
    ))
    session.flush()

    period = _mk_period(session)
    shift = _mk_shift(session, overtime_requires_approval=False)
    day = _mk_day(session, emp, date(2026, 1, 5), shift_id=shift.id)
    _mk_seg(session, day, kind="overtime", day_type="weekday", tier=1,
            minutes=60, rate_value="1.5", overtime_status="approved")

    lines, _, _ = _build_attendance_earnings(session, emp, period)
    ot_lines = [l for l in lines if (l.source_ref or {}).get("earning_type_code") == "overtime_t1"]
    assert len(ot_lines) == 1
    assert ot_lines[0].amount == Decimal("216.35")


# ---------------------------------------------------------------------------
# Overtime approval gate (round-2 §6)
# ---------------------------------------------------------------------------

def test_attendance_earnings_overtime_unapproved_skipped_with_warning(session):
    _mk_company(session)
    _mk_earning_type(session, code="overtime_t1")
    _mk_settings(
        session,
        attendance_earning_map={"overtime|weekday|1": "overtime_t1"},
    )
    emp = _mk_employee(session)
    period = _mk_period(session)
    shift = _mk_shift(session, overtime_requires_approval=True)
    day = _mk_day(session, emp, date(2026, 1, 5), shift_id=shift.id)
    _mk_seg(session, day, kind="overtime", day_type="weekday", tier=1,
            minutes=60, overtime_status=None)

    lines, warnings, _ = _build_attendance_earnings(session, emp, period)
    assert lines == []
    assert any("overtime_unapproved" in w for w in warnings)


def test_attendance_earnings_overtime_approved_paid(session):
    _mk_company(session)
    _mk_earning_type(session, code="overtime_t1")
    _mk_settings(
        session,
        attendance_earning_map={"overtime|weekday|1": "overtime_t1"},
    )
    emp = _mk_employee(session)
    period = _mk_period(session)
    shift = _mk_shift(session, overtime_requires_approval=True)
    day = _mk_day(session, emp, date(2026, 1, 5), shift_id=shift.id)
    _mk_seg(session, day, kind="overtime", day_type="weekday", tier=1,
            minutes=60, rate_value="1.5", overtime_status="approved")

    lines, warnings, _ = _build_attendance_earnings(session, emp, period)
    assert len(lines) == 1
    assert lines[0].amount == Decimal("150.00")
    assert not any("overtime_unapproved" in w for w in warnings)


# ---------------------------------------------------------------------------
# Unpaid day (round-2 §3)
# ---------------------------------------------------------------------------

def test_attendance_earnings_unpaid_day_behaviour_unset_409(session):
    _mk_company(session)
    _mk_settings(session, unpaid_day_behaviour=None)
    emp = _mk_employee(session, pay_basis="monthly", base_rate=None,
                       contracted_weekly_hours=40.0)
    period = _mk_period(session)
    _mk_day(session, emp, date(2026, 1, 5), status="absent")

    with pytest.raises(AppError) as exc:
        _build_attendance_earnings(session, emp, period)
    assert exc.value.code == "unpaid_day_behaviour_not_configured"


def test_attendance_earnings_unpaid_day_monthly_negates_gross(session):
    _mk_company(session)
    _mk_earning_type(session, code="BASE_MONTHLY")
    _mk_settings(
        session,
        unpaid_day_behaviour="deduct_daily",
        unpaid_day_formula_code="gen_unpaid_absence",
        monthly_hourly_derivation_formula_code="hourly_rate_from_monthly",
    )
    shift = _mk_shift(session, length_minutes=480)
    emp = _mk_employee(session, pay_basis="monthly", base_rate=None,
                       contracted_weekly_hours=40.0, default_shift_id=shift.id)
    from app.db.tenant.models.pay import EmployeeEarning
    base_et = session.scalar(select(EarningType).where(EarningType.code == "BASE_MONTHLY"))
    session.add(EmployeeEarning(
        id=uuid.uuid4(),
        employee_id=emp.id,
        earning_type_id=base_et.id,
        amount=Decimal("25000.00"),
        effective_from=date(2024, 1, 1),
        is_active=True,
        row_version=1,
    ))
    session.flush()

    period = _mk_period(session)
    _mk_day(session, emp, date(2026, 1, 5), status="absent")

    lines, _, _ = _build_attendance_earnings(session, emp, period)
    unpaid = [l for l in lines if (l.source_ref or {}).get("kind") == "unpaid_day"]
    assert len(unpaid) == 1
    assert unpaid[0].amount < Decimal("0.00")


# ---------------------------------------------------------------------------
# Leave source (round-2 §9)
# ---------------------------------------------------------------------------

def test_attendance_earnings_leave_source_not_adjustment_422(session):
    _mk_company(session)
    _mk_settings(session, leave_authoritative_source="leave_request")
    emp = _mk_employee(session)
    period = _mk_period(session)

    with pytest.raises(AppError) as exc:
        _build_attendance_earnings(session, emp, period)
    assert exc.value.code == "leave_source_not_available"


def test_attendance_earnings_leave_adjustment_earns_leave_paid_hourly(session):
    _mk_company(session)
    _mk_earning_type(session, code="leave_paid")
    _mk_settings(
        session,
        leave_authoritative_source="adjustment",
        leave_earning_for_monthly=False,
    )
    shift = _mk_shift(session, length_minutes=480)
    emp = _mk_employee(session, default_shift_id=shift.id)
    period = _mk_period(session)
    _mk_day(session, emp, date(2026, 1, 5), status="leave")

    lines, _, _ = _build_attendance_earnings(session, emp, period)
    leave = [l for l in lines if (l.source_ref or {}).get("kind") == "paid_leave"]
    assert len(leave) == 1
    assert leave[0].amount == Decimal("800.00")


# ---------------------------------------------------------------------------
# Snapshot (round-2 §10)
# ---------------------------------------------------------------------------

def test_attendance_earnings_snapshot_captures_inputs(session):
    _mk_company(session)
    _mk_earning_type(session, code="hourly_normal")
    _mk_settings(
        session,
        attendance_earning_map={"normal|weekday|any": "hourly_normal"},
    )
    emp = _mk_employee(session)
    period = _mk_period(session)
    day = _mk_day(session, emp, date(2026, 1, 5))
    _mk_seg(session, day, kind="normal", day_type="weekday", minutes=480)

    _lines, _warnings, snap = _build_attendance_earnings(session, emp, period)
    assert snap["grouped_minutes"].get("normal|weekday|any") == 480
    assert snap["mapping_used"]["normal|weekday|any"] == "hourly_normal"
    assert "rates_by_date" in snap
    assert "settings" in snap


# ---------------------------------------------------------------------------
# End-to-end pipeline (round-2 §8)
# ---------------------------------------------------------------------------

def _fake_pipeline_config() -> P.PipelineConfig:
    return P.PipelineConfig(
        tax_engine=T.default_engine(),
        tax_tables=T.TaxTables(
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
        ),
        uif_rows=[
            {"row_key": "employee_rate", "value": "0.01"},
            {"row_key": "employer_rate", "value": "0.01"},
            {"row_key": "monthly_ceiling", "value": "100000"},
        ],
        sdl_rows=[
            {"row_key": "rate", "value": "0.01"},
            {"row_key": "exemption_threshold_annual", "value": "50000"},
        ],
        retirement_rows=[
            {"row_key": "percentage_of_taxable_income", "value": "0.10"},
            {"row_key": "annual_cap", "value": "1000"},
        ],
        periods_per_year=12,
        employee_age=40,
        medical_members=0,
        uif_exempt=False,
        sdl_applies=True,
        net_pay_floor=Decimal("0.00"),
    )


def test_attendance_earnings_end_to_end_hourly_gross_paye_net(session):
    _mk_company(session)
    _mk_earning_type(session, code="hourly_normal")
    _mk_settings(
        session,
        attendance_earning_map={"normal|weekday|any": "hourly_normal"},
    )
    emp = _mk_employee(session, pay_basis="hourly", base_rate="100.00")
    period = _mk_period(session)
    day = _mk_day(session, emp, date(2026, 1, 5))
    _mk_seg(session, day, kind="normal", day_type="weekday", minutes=480)

    earnings, _warnings, _snap = _build_attendance_earnings(session, emp, period)
    assert len(earnings) == 1
    assert earnings[0].amount == Decimal("800.00")

    draft = P.run_pipeline(_fake_pipeline_config(), earnings, [])
    assert not draft.refused
    assert draft.gross == Decimal("800.00")
    assert draft.uif_employee == Decimal("8.00")
    assert draft.paye > Decimal("0.00")
    assert Decimal("0.00") < draft.net < draft.gross
