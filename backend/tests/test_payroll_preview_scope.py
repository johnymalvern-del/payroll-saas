"""M6 Stage A — preview RESPONSE scope filter.

Verifies that POST /payroll/pay-periods/{id}/preview scope-filters the
HTTP response via apply_scope(Payslip.employee_id), while leaving the
underlying calculation company-wide (run_preview / _in_scope_employees
unchanged). The calc-wide behaviour is proven separately in
test_payroll_pay_periods.py (test_preview_persists_preview_rows) which
runs the real pipeline.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.v1.payroll_pay_periods import preview_employee, preview_pay_period
from app.core.errors import AppError
from app.db.tenant.models.organisation import Branch, Department
from app.db.tenant.models.pay import PayPeriod, PayrollRun, Payslip
from app.db.tenant.models.people import Employee, User, UserScope


@pytest.fixture()
def session(_leave_session_shared):
    return _leave_session_shared


def _mk_branch(session, branch_id: uuid.UUID | None = None) -> uuid.UUID:
    """Get-or-create a Branch row so Employee.branch_id FK is satisfiable."""
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


def _mk_department(session, dept_id: uuid.UUID | None = None) -> uuid.UUID:
    """Get-or-create a Department row so Employee.department_id FK is satisfiable."""
    did = dept_id or uuid.uuid4()
    if session.get(Department, did) is not None:
        return did
    session.add(Department(
        id=did,
        name=f"Department {did.hex[:12]}",
        code=f"D-{did.hex[:12]}",
        parent_id=None,
        is_active=True,
        row_version=1,
    ))
    session.flush()
    return did


def _mk_employee(session, code, branch_id, department_id=None):
    _mk_branch(session, branch_id)  # ensure FK target exists first
    if department_id is not None:
        _mk_department(session, department_id)
    emp = Employee(
        employee_code=code,
        first_name="Test",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status="active",
        pay_basis="monthly",
        pay_frequency="monthly",
        branch_id=branch_id,
        department_id=department_id,
        row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


def _mk_period(session):
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"PS-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        pay_date=date(2026, 12, 5),
        status="open",
        cutoff_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
        row_version=1,
    )
    session.add(p)
    session.flush()
    return p


def _mk_user(session, role):
    u = User(
        id=uuid.uuid4(),
        username=f"{role}-{uuid.uuid4().hex[:6]}",
        password_hash="x",
        role=role,
        is_active=True,
        must_change_password=False,
        row_version=1,
    )
    session.add(u)
    session.flush()
    return u


def _mk_scope(session, user, scope_type, scope_id):
    session.add(UserScope(
        id=uuid.uuid4(),
        user_id=user.id,
        scope_type=scope_type,
        scope_id=scope_id,
    ))
    session.flush()


def _mk_run_with_payslips(session, period, employees):
    run = PayrollRun(
        id=uuid.uuid4(),
        pay_period_id=period.id,
        kind="preview",
        revision=1,
        status="completed",
        rules_snapshot={
            "employee_count": len(employees),
            "unacknowledged_formulas": [],
        },
    )
    session.add(run)
    session.flush()
    for emp in employees:
        session.add(Payslip(
            id=uuid.uuid4(),
            payroll_run_id=run.id,
            pay_period_id=period.id,
            employee_id=emp.id,
            revision=1,
            status="preview",
            gross=Decimal("1000.00"),
            pre_tax_deductions=Decimal("0.00"),
            taxable_income=Decimal("1000.00"),
            paye=Decimal("100.00"),
            uif_employee=Decimal("0.00"),
            uif_employer=Decimal("0.00"),
            sdl=Decimal("0.00"),
            other_deductions=Decimal("0.00"),
            reimbursements=Decimal("0.00"),
            net=Decimal("900.00"),
            employer_costs={},
            snapshot={},
            calculation_context={},
        ))
    session.flush()
    return run


def _patch_run_preview(monkeypatch, run):
    from app.api.v1 import payroll_pay_periods
    monkeypatch.setattr(
        payroll_pay_periods, "run_preview",
        lambda db, user, period: run,
    )


def _count_payslips(session, run_id):
    return session.scalar(
        select(func.count()).select_from(Payslip).where(Payslip.payroll_run_id == run_id)
    ) or 0


# 1 — payroll_admin sees all
def test_payroll_admin_sees_all_employees(session, monkeypatch):
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", uuid.uuid4())
    emp_b = _mk_employee(session, "EB", uuid.uuid4())
    run = _mk_run_with_payslips(session, period, [emp_a, emp_b])
    _patch_run_preview(monkeypatch, run)
    admin = _mk_user(session, "payroll_admin")
    out = preview_pay_period(period.id, session, admin, limit=100, cursor=None)
    assert {i.employee_id for i in out.items} == {emp_a.id, emp_b.id}
    assert out.raw_employee_count == 2


# 2 — HR without scope rows: fail-open preserved
def test_hr_no_scope_rows_sees_all(session, monkeypatch):
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", uuid.uuid4())
    emp_b = _mk_employee(session, "EB", uuid.uuid4())
    run = _mk_run_with_payslips(session, period, [emp_a, emp_b])
    _patch_run_preview(monkeypatch, run)
    hr = _mk_user(session, "hr")
    out = preview_pay_period(period.id, session, hr, limit=100, cursor=None)
    assert {i.employee_id for i in out.items} == {emp_a.id, emp_b.id}


# 3 — branch A HR: response filtered
def test_hr_branch_a_preview_only_sees_branch_a(session, monkeypatch):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    run = _mk_run_with_payslips(session, period, [emp_a, emp_b])
    _patch_run_preview(monkeypatch, run)
    hr = _mk_user(session, "hr")
    _mk_scope(session, hr, "branch", branch_a)
    out = preview_pay_period(period.id, session, hr, limit=100, cursor=None)
    assert {i.employee_id for i in out.items} == {emp_a.id}
    assert out.raw_employee_count == 2
    # Underlying run still has BOTH payslips — calc is company-wide
    assert _count_payslips(session, run.id) == 2


# 4 — branch B HR trigger after branch A does not corrupt company-wide calc
def test_branch_b_hr_trigger_after_branch_a_keeps_full_calc(session, monkeypatch):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    run = _mk_run_with_payslips(session, period, [emp_a, emp_b])
    _patch_run_preview(monkeypatch, run)
    hr_a = _mk_user(session, "hr")
    _mk_scope(session, hr_a, "branch", branch_a)
    hr_b = _mk_user(session, "hr")
    _mk_scope(session, hr_b, "branch", branch_b)
    out_a = preview_pay_period(period.id, session, hr_a, limit=100, cursor=None)
    assert {i.employee_id for i in out_a.items} == {emp_a.id}
    out_b = preview_pay_period(period.id, session, hr_b, limit=100, cursor=None)
    assert {i.employee_id for i in out_b.items} == {emp_b.id}
    assert _count_payslips(session, run.id) == 2


# 5 — empty-resolving scope returns no rows, calc untouched
def test_empty_scope_hr_gets_empty_items_full_calc(session, monkeypatch):
    branch_a, branch_b, branch_empty = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    run = _mk_run_with_payslips(session, period, [emp_a, emp_b])
    _patch_run_preview(monkeypatch, run)
    hr = _mk_user(session, "hr")
    _mk_scope(session, hr, "branch", branch_empty)
    out = preview_pay_period(period.id, session, hr, limit=100, cursor=None)
    assert out.items == []
    assert out.raw_employee_count == 2
    assert _count_payslips(session, run.id) == 2


# 6 — department scope
def test_department_scope_hr_sees_department_only(session, monkeypatch):
    branch = uuid.uuid4()
    dept_x, dept_y = uuid.uuid4(), uuid.uuid4()
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", branch, dept_x)
    emp_b = _mk_employee(session, "EB", branch, dept_y)
    run = _mk_run_with_payslips(session, period, [emp_a, emp_b])
    _patch_run_preview(monkeypatch, run)
    hr = _mk_user(session, "hr")
    _mk_scope(session, hr, "department", dept_x)
    out = preview_pay_period(period.id, session, hr, limit=100, cursor=None)
    assert {i.employee_id for i in out.items} == {emp_a.id}


# 7 — individual detail 404 for out-of-scope (regression of existing behaviour)
def test_individual_out_of_scope_preview_detail_404(session, monkeypatch):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    _mk_run_with_payslips(session, period, [emp_a, emp_b])
    hr = _mk_user(session, "hr")
    _mk_scope(session, hr, "branch", branch_a)
    with pytest.raises(AppError) as e:
        preview_employee(period.id, emp_b.id, session, hr)
    assert e.value.code == "not_found"


# 8 — M5 sheet unchanged after scoped-HR trigger
def test_m5_salary_sheet_unchanged_after_scoped_hr_preview(session, monkeypatch):
    from app.api.v1.payroll_pay_periods import get_salary_sheet
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    run = _mk_run_with_payslips(session, period, [emp_a, emp_b])
    _patch_run_preview(monkeypatch, run)
    hr = _mk_user(session, "hr")
    _mk_scope(session, hr, "branch", branch_a)
    admin = _mk_user(session, "payroll_admin")
    preview_pay_period(period.id, session, hr, limit=100, cursor=None)
    sheet = get_salary_sheet(period.id, session, admin, q=None, limit=100, cursor=None)
    assert {i.employee_id for i in sheet.items} == {emp_a.id, emp_b.id}


# 9 — pagination respects scope
def test_preview_pagination_respects_scope(session, monkeypatch):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    period = _mk_period(session)
    emp_a1 = _mk_employee(session, "EA1", branch_a)
    emp_a2 = _mk_employee(session, "EA2", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    run = _mk_run_with_payslips(session, period, [emp_a1, emp_a2, emp_b])
    _patch_run_preview(monkeypatch, run)
    hr = _mk_user(session, "hr")
    _mk_scope(session, hr, "branch", branch_a)
    page1 = preview_pay_period(period.id, session, hr, limit=1, cursor=None)
    assert len(page1.items) == 1
    assert page1.items[0].employee_id in {emp_a1.id, emp_a2.id}
    assert page1.next_cursor is not None
    page2 = preview_pay_period(period.id, session, hr, limit=1, cursor=page1.next_cursor)
    assert len(page2.items) == 1
    assert page2.items[0].employee_id in {emp_a1.id, emp_a2.id}
    assert page2.items[0].employee_id != page1.items[0].employee_id
    assert page2.next_cursor is None


# 10 — invariant sentinel: response filtered but calc-wide preserved
def test_preview_scope_filtered_via_response_not_calc(session, monkeypatch):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    period = _mk_period(session)
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    run = _mk_run_with_payslips(session, period, [emp_a, emp_b])
    _patch_run_preview(monkeypatch, run)
    hr = _mk_user(session, "hr")
    _mk_scope(session, hr, "branch", branch_a)
    out = preview_pay_period(period.id, session, hr, limit=100, cursor=None)
    assert {i.employee_id for i in out.items} == {emp_a.id}
    all_ps = session.scalars(
        select(Payslip).where(Payslip.payroll_run_id == run.id)
    ).all()
    assert {p.employee_id for p in all_ps} == {emp_a.id, emp_b.id}