"""M6-BE-1 / M5 — salary-sheet endpoint tests (extended by M6 Stage A).

Covers: permission matrix, preview/finalised figures_state, basic vs
additional split from PayslipLine, reconciliation with Payslip totals,
empty periods, employee search, cursor pagination, and M6 Stage A's
preview_out_of_scope state.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.v1.payroll_pay_periods import get_salary_sheet
from app.core.errors import AppError
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.db.tenant.models.organisation import Branch
from app.db.tenant.models.pay import (
    PayPeriod, PayrollRun, Payslip, PayslipLine,
)
from app.db.tenant.models.people import Employee, User, UserScope


@pytest.fixture()
def session(request):
    for name in (
        "_leave_session_shared",
        "_payroll_session_shared",
        "_session_shared",
        "session_shared",
        "db_session",
    ):
        try:
            return request.getfixturevalue(name)
        except pytest.FixtureLookupError:
            continue
    pytest.skip(
        "No shared session fixture found among "
        "(_leave_session_shared, _payroll_session_shared, "
        "_session_shared, session_shared, db_session) — pass one in "
        "conftest.py or extend this list"
    )


def _admin():
    return SimpleNamespace(
        id=uuid.uuid4(), role="payroll_admin", employee_id=None,
    )


def _mk_branch(session, branch_id: uuid.UUID | None = None) -> uuid.UUID:
    """Get-or-create a Branch row so Employee.branch_id FK is satisfiable.

    Idempotent: safe when two employees share a branch or when a test
    pre-creates one before wiring emp.branch_id.
    """
    bid = branch_id or uuid.uuid4()
    if session.get(Branch, bid) is not None:
        return bid
    session.add(Branch(
        id=bid,
        name=f"Branch {bid.hex[:12]}",
        code=f"B-{bid.hex[:12]}",
        is_active=True,
        row_version=1,
    ))
    session.flush()
    return bid


def _mk_period(
    session, *, period_key: str = "2026-11", status: str = "open",
) -> PayPeriod:
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=period_key,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        pay_date=date(2026, 11, 30),
        status=status,
        cutoff_at=datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc),
        row_version=1,
    )
    session.add(p)
    session.flush()
    return p


def _mk_run(
    session, period: PayPeriod, *, kind: str = "preview", revision: int = 1,
) -> PayrollRun:
    r = PayrollRun(
        id=uuid.uuid4(),
        pay_period_id=period.id,
        kind=kind,
        revision=revision,
        status="completed",
        rules_snapshot={},
    )
    session.add(r)
    session.flush()
    return r


def _mk_employee(session, code: str = "E1") -> Employee:
    e = Employee(
        id=uuid.uuid4(),
        employee_code=code,
        first_name="Test",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status="active",
        pay_basis="monthly",
        pay_frequency="monthly",
        overtime_eligible=False,
        clocks=False,
        employee_type="salaried",
        medical_scheme_members=0,
        uif_exempt=False,
        medical_aid_dependants=0,
        row_version=1,
    )
    session.add(e)
    session.flush()
    return e


def _mk_payslip(
    session,
    *,
    period: PayPeriod,
    run: PayrollRun,
    emp: Employee,
    status: str = "preview",
    gross: Decimal = Decimal("15000.00"),
    pre_tax: Decimal = Decimal("1000.00"),
    taxable: Decimal = Decimal("14000.00"),
    paye: Decimal = Decimal("3000.00"),
    uif_emp: Decimal = Decimal("177.12"),
    uif_er: Decimal = Decimal("177.12"),
    sdl: Decimal = Decimal("150.00"),
    other: Decimal = Decimal("200.00"),
    reimb: Decimal = Decimal("0.00"),
    net: Decimal = Decimal("10622.88"),
) -> Payslip:
    ps = Payslip(
        id=uuid.uuid4(),
        payroll_run_id=run.id,
        pay_period_id=period.id,
        employee_id=emp.id,
        revision=run.revision,
        status=status,
        gross=gross,
        pre_tax_deductions=pre_tax,
        taxable_income=taxable,
        paye=paye,
        uif_employee=uif_emp,
        uif_employer=uif_er,
        sdl=sdl,
        other_deductions=other,
        reimbursements=reimb,
        net=net,
        employer_costs={},
        snapshot={},
        calculation_context={},
    )
    session.add(ps)
    session.flush()
    return ps


def _mk_line(
    session,
    *,
    payslip: Payslip,
    label: str,
    amount: Decimal,
    earning_code: str,
    sort_order: int = 0,
) -> PayslipLine:
    l = PayslipLine(
        id=uuid.uuid4(),
        payslip_id=payslip.id,
        line_type="earning",
        step="gross",
        sort_order=sort_order,
        label=label,
        amount=amount,
        source_ref={"earning_type_code": earning_code, "rate_source": "employee_earning"},
    )
    session.add(l)
    session.flush()
    return l


# ─────────────────────────────────────────────────────────────────────
# Permission matrix — no DB required, always runs
# ─────────────────────────────────────────────────────────────────────


def test_payroll_preview_permission_matrix():
    assert Permission.PAYROLL_PREVIEW not in ROLE_PERMISSIONS["employee"]
    assert Permission.PAYROLL_PREVIEW not in ROLE_PERMISSIONS["manager"]
    assert Permission.PAYROLL_PREVIEW not in ROLE_PERMISSIONS["auditor"]
    assert Permission.PAYROLL_PREVIEW in ROLE_PERMISSIONS["hr"]
    assert Permission.PAYROLL_PREVIEW in ROLE_PERMISSIONS["payroll_admin"]


# ─────────────────────────────────────────────────────────────────────
# DB-dependent tests (existing)
# ─────────────────────────────────────────────────────────────────────


def test_payroll_admin_sees_all_payslips(session):
    period = _mk_period(session)
    run = _mk_run(session, period)
    emp1 = _mk_employee(session, code="E1")
    emp2 = _mk_employee(session, code="E2")
    _mk_payslip(session, period=period, run=run, emp=emp1)
    _mk_payslip(session, period=period, run=run, emp=emp2)
    session.commit()

    out = get_salary_sheet(period_id=period.id, db=session, user=_admin())
    assert len(out.items) == 2
    codes = {i.employee_code for i in out.items}
    assert codes == {"E1", "E2"}
    assert out.figures_state == "preview"


def test_open_period_with_no_preview_returns_no_preview(session):
    period = _mk_period(session)
    session.commit()
    out = get_salary_sheet(period_id=period.id, db=session, user=_admin())
    assert out.items == []
    assert out.figures_state == "no_preview"


def test_locked_period_uses_current_payslips(session):
    period = _mk_period(session, status="locked")
    run = _mk_run(session, period, kind="final")
    emp = _mk_employee(session, code="E1")
    _mk_payslip(session, period=period, run=run, emp=emp, status="current")
    session.commit()
    out = get_salary_sheet(period_id=period.id, db=session, user=_admin())
    assert out.figures_state == "finalised"
    assert len(out.items) == 1
    assert out.items[0].payslip_status == "current"


def test_basic_and_additional_split_from_payslip_lines(session):
    period = _mk_period(session)
    run = _mk_run(session, period)
    emp = _mk_employee(session, code="E1")
    ps = _mk_payslip(session, period=period, run=run, emp=emp)
    _mk_line(
        session, payslip=ps, label="Base monthly",
        amount=Decimal("14500.00"), earning_code="BASE_MONTHLY",
        sort_order=0,
    )
    _mk_line(
        session, payslip=ps, label="Transport",
        amount=Decimal("500.00"), earning_code="TRANSPORT",
        sort_order=1,
    )
    session.commit()
    out = get_salary_sheet(period_id=period.id, db=session, user=_admin())
    row = out.items[0]
    assert row.basic_earnings == Decimal("14500.00")
    assert row.additional_earnings == Decimal("500.00")
    assert row.basic_earnings + row.additional_earnings == row.gross


def test_reconciles_with_payslip_fields(session):
    period = _mk_period(session)
    run = _mk_run(session, period)
    emp = _mk_employee(session, code="E1")
    _mk_payslip(session, period=period, run=run, emp=emp)
    session.commit()
    out = get_salary_sheet(period_id=period.id, db=session, user=_admin())
    row = out.items[0]
    ps = session.query(Payslip).filter(Payslip.employee_id == emp.id).one()
    assert row.gross == ps.gross
    assert row.paye == ps.paye
    assert row.uif_employee == ps.uif_employee
    assert row.uif_employer == ps.uif_employer
    assert row.sdl == ps.sdl
    assert row.net == ps.net
    assert row.pre_tax_deductions == ps.pre_tax_deductions
    assert row.taxable_income == ps.taxable_income
    assert row.other_deductions == ps.other_deductions
    assert row.reimbursements == ps.reimbursements


def test_search_by_employee_code(session):
    period = _mk_period(session)
    run = _mk_run(session, period)
    emp1 = _mk_employee(session, code="EMP-A")
    emp2 = _mk_employee(session, code="EMP-B")
    _mk_payslip(session, period=period, run=run, emp=emp1)
    _mk_payslip(session, period=period, run=run, emp=emp2)
    session.commit()
    out = get_salary_sheet(
        period_id=period.id, db=session, user=_admin(), q="EMP-A",
    )
    assert len(out.items) == 1
    assert out.items[0].employee_code == "EMP-A"


def test_cursor_pagination(session):
    period = _mk_period(session)
    run = _mk_run(session, period)
    for code in ("E1", "E2", "E3"):
        emp = _mk_employee(session, code=code)
        _mk_payslip(session, period=period, run=run, emp=emp)
    session.commit()
    first = get_salary_sheet(
        period_id=period.id, db=session, user=_admin(), limit=2,
    )
    assert len(first.items) == 2
    assert first.next_cursor is not None
    second = get_salary_sheet(
        period_id=period.id, db=session, user=_admin(), limit=2,
        cursor=first.next_cursor,
    )
    assert len(second.items) == 1
    assert second.next_cursor is None


def test_period_not_found(session):
    with pytest.raises(AppError) as e:
        get_salary_sheet(
            period_id=uuid.uuid4(), db=session, user=_admin(),
        )
    assert e.value.code == "not_found"


# ─────────────────────────────────────────────────────────────────────
# M6 Stage A additions — preview_out_of_scope state
# ─────────────────────────────────────────────────────────────────────


def _mk_hr_user(session, scope_type: str, scope_id: uuid.UUID) -> User:
    u = User(
        id=uuid.uuid4(),
        username=f"hr-{uuid.uuid4().hex[:6]}",
        password_hash="x",
        role="hr",
        is_active=True,
        must_change_password=False,
        row_version=1,
    )
    session.add(u)
    session.flush()
    session.add(UserScope(
        id=uuid.uuid4(),
        user_id=u.id,
        scope_type=scope_type,
        scope_id=scope_id,
    ))
    session.flush()
    return u


def test_preview_out_of_scope_state(session):
    """Preview exists but caller's scope resolves to zero employees."""
    branch_a, branch_b, branch_empty = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _mk_branch(session, branch_a)
    _mk_branch(session, branch_b)
    period = _mk_period(session)
    run = _mk_run(session, period)
    emp_a = _mk_employee(session, code="EA")
    emp_b = _mk_employee(session, code="EB")
    emp_a.branch_id = branch_a
    emp_b.branch_id = branch_b
    session.flush()
    _mk_payslip(session, period=period, run=run, emp=emp_a)
    _mk_payslip(session, period=period, run=run, emp=emp_b)
    hr = _mk_hr_user(session, "branch", branch_empty)
    out = get_salary_sheet(
        period_id=period.id, db=session, user=hr, q=None,
        limit=100, cursor=None,
    )
    assert out.items == []
    assert out.figures_state == "preview_out_of_scope"


def test_preview_out_of_scope_state_locked_period_returns_finalised(session):
    """Locked period + empty in-scope result keeps figures_state=finalised."""
    branch_a, branch_b, branch_empty = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _mk_branch(session, branch_a)
    _mk_branch(session, branch_b)
    period = _mk_period(session, status="locked")
    run = _mk_run(session, period, kind="final")
    emp_a = _mk_employee(session, code="EA")
    emp_b = _mk_employee(session, code="EB")
    emp_a.branch_id = branch_a
    emp_b.branch_id = branch_b
    session.flush()
    _mk_payslip(session, period=period, run=run, emp=emp_a, status="current")
    _mk_payslip(session, period=period, run=run, emp=emp_b, status="current")
    hr = _mk_hr_user(session, "branch", branch_empty)
    out = get_salary_sheet(
        period_id=period.id, db=session, user=hr, q=None,
        limit=100, cursor=None,
    )
    assert out.items == []
    assert out.figures_state == "finalised"