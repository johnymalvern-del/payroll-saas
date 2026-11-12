"""M6 Part 2 Stage 2 & 2b — locked-period guards.

Stage 2 (already covered): CR approval via `_apply` in
payroll_change_request.py is refused with 409 `locked_period_affects` if
the CR's effective window overlaps a locked period.

Stage 2b (this file): salary-assignment approval is refused with 409
`locked_period_affects` if any locked period's `end_date >=
assignment.effective_from`. Mirrors the CR-guard code so client handling is
uniform.

Note on test design: `approve_assignment` runs `self_approval_forbidden`
and `validate_date_rules` BEFORE the locked-period guard. So Stage 2b
tests must (a) use distinct submitter and approver users, and (b) provide
a "closed" base period at future dates (mirrors _mk_valid_env from
test_salary_assignment_approve.py) so `validate_date_rules` passes before
the guard runs. Test 1 blocks via "effective_from before a future locked
period" — a case `validate_date_rules` cannot catch but the guard must.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.pay import (
    EarningType, EmployeeEarning, PayPeriod, PayrollRun, Payslip,
)
from app.db.tenant.models.people import Employee, User
from app.services.payroll_change_request import approve_change_request
from app.services.salary_assignment_approve_service import approve_assignment
from app.services.salary_assignment_service import submit_assignment
from app.services.salary_structure_service import create_structure


@pytest.fixture()
def db(_leave_session_shared, monkeypatch):
    """Per-test session with commit redirected to flush.

    Salary-assignment approve commits internally; redirect to flush so the
    test runs inside _leave_session_shared's rolled-back transaction.
    """
    s = _leave_session_shared
    monkeypatch.setattr(s, "commit", lambda: s.flush())
    return s


@pytest.fixture()
def admin(db):
    u = User(
        id=uuid.uuid4(),
        username=f"pa-{uuid.uuid4().hex[:12]}",
        password_hash="x",
        role="payroll_admin",
        is_active=True,
        must_change_password=False,
        row_version=1,
    )
    db.add(u); db.flush()
    return SimpleNamespace(id=u.id, role="payroll_admin", employee_id=None)


def _mk_submitter(db):
    """A distinct payroll_admin user for submission.

    approve_assignment refuses if submitted_by_user_id == approver.id, so
    Stage 2b tests must not submit and approve with the same user.
    """
    u = User(
        id=uuid.uuid4(),
        username=f"sub-{uuid.uuid4().hex[:12]}",
        password_hash="x",
        role="payroll_admin",
        is_active=True,
        must_change_password=False,
        row_version=1,
    )
    db.add(u); db.flush()
    return SimpleNamespace(id=u.id, role="payroll_admin", employee_id=None)


# ---------------------------------------------------------------------------
# Helpers — CR side
# ---------------------------------------------------------------------------

def _mk_employee(session, *, pay_basis="monthly"):
    code = f"E{uuid.uuid4().hex[:6]}"
    emp = Employee(
        employee_code=code, first_name="T", last_name=code,
        hire_date=date(2024, 1, 1), status="active",
        employee_type="monthly" if pay_basis == "monthly" else "hourly",
        pay_basis=pay_basis,
        pay_frequency="monthly", row_version=1,
    )
    session.add(emp); session.flush()
    return emp


def _mk_period(session, *, start, end, pay_date=None, status="closed"):
    if pay_date is None:
        pay_date = end + timedelta(days=5)
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"P{uuid.uuid4().hex[:12]}",
        start_date=start,
        end_date=end,
        pay_date=pay_date,
        status=status,
        cutoff_at=datetime.combine(end, datetime.min.time()).replace(tzinfo=timezone.utc),
        row_version=1,
    )
    session.add(p); session.flush()
    return p


def _mk_closed_period(session, *, start, end):
    return _mk_period(session, start=start, end=end, status="closed")


def _mk_locked_period(session, *, start, end):
    return _mk_period(session, start=start, end=end, status="locked")


def _mk_open_period(session, *, start, end):
    return _mk_period(session, start=start, end=end, status="open")


def _mk_valid_base_period(db):
    """Mirror _mk_valid_env from test_salary_assignment_approve.py.

    Creates a closed period at [today+10, today+16] and returns today+17.
    The assignment submitted with this effective_from is known to pass
    validate_date_rules in the existing test suite.
    """
    d0 = date.today()
    s = d0 + timedelta(days=10)
    e = s + timedelta(days=6)
    _mk_closed_period(db, start=s, end=e)
    return e + timedelta(days=1)  # d0 + 17


def _mk_locked_payslip(session, employee, period):
    run = PayrollRun(
        id=uuid.uuid4(),
        pay_period_id=period.id,
        kind="final",
        revision=1,
        status="completed",
        rules_snapshot={},
    )
    session.add(run); session.flush()
    ps = Payslip(
        id=uuid.uuid4(),
        payroll_run_id=run.id,
        pay_period_id=period.id,
        employee_id=employee.id,
        revision=1, status="current",
        gross=Decimal("1000"), pre_tax_deductions=Decimal("0"),
        taxable_income=Decimal("1000"), paye=Decimal("100"),
        uif_employee=Decimal("0"), uif_employer=Decimal("0"), sdl=Decimal("0"),
        other_deductions=Decimal("0"), reimbursements=Decimal("0"),
        net=Decimal("900"), employer_costs={}, snapshot={}, calculation_context={},
    )
    session.add(ps); session.flush()
    return ps


def _mk_earning_type(session):
    et = EarningType(
        id=uuid.uuid4(), name="Base", code=f"b-{uuid.uuid4().hex[:12]}",
        calc_method="fixed_amount", frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        is_system=False, is_active=True, row_version=1,
    )
    session.add(et); session.flush()
    return et


def _mk_earning(session, employee, et, *, effective_from, effective_to=None):
    er = EmployeeEarning(
        id=uuid.uuid4(), employee_id=employee.id, earning_type_id=et.id,
        amount=Decimal("1000.00"), rate=None,
        effective_from=effective_from, effective_to=effective_to,
        is_active=True, row_version=1,
    )
    session.add(er); session.flush()
    return er


def _mk_cr(session, *, kind, employee_id, payload):
    cr = PayrollChangeRequest(
        id=uuid.uuid4(),
        kind=kind,
        employee_id=employee_id,
        payload=payload,
        status="pending",
        requested_by_user_id=None,
        row_version=1,
    )
    session.add(cr); session.flush()
    return cr


# ---------------------------------------------------------------------------
# Helpers — salary-assignment side
# ---------------------------------------------------------------------------

def _mk_structure(db, admin, *,
                  pay_basis="monthly",
                  base_rate="15000",
                  components=None):
    return create_structure(
        db, admin,
        name=f"S{uuid.uuid4().hex[:6]}",
        description=None,
        pay_basis=pay_basis,
        base_rate=Decimal(base_rate),
        components=components or [],
    )


def _submit_assignment(db, submitter, emp, structure, effective_from):
    return submit_assignment(
        db, submitter,
        employee_id=emp.id,
        structure_id=structure.id,
        effective_from=effective_from,
        idempotency_key=None,
        override_manual_ids=[],
    )


# ===========================================================================
# Stage 2 — CR approval guard (unchanged)
# ===========================================================================


def test_earning_create_affects_locked_blocks(db, admin):
    emp = _mk_employee(db)
    period = _mk_locked_period(db, start=date(2026, 11, 1), end=date(2026, 11, 30))
    et = _mk_earning_type(db)
    cr = _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "500.00",
            "effective_from": "2026-11-15",
        },
    )
    with pytest.raises(AppError) as e:
        approve_change_request(db, admin, cr.id)
    assert e.value.code == "locked_period_affects"
    assert e.value.details["period_id"] == str(period.id)


def test_earning_update_existing_overlaps_blocks(db, admin):
    emp = _mk_employee(db)
    _mk_locked_period(db, start=date(2026, 11, 1), end=date(2026, 11, 30))
    et = _mk_earning_type(db)
    earning = _mk_earning(
        db, emp, et, effective_from=date(2026, 1, 1), effective_to=None,
    )
    cr = _mk_cr(
        db, kind="employee_earning_update", employee_id=emp.id,
        payload={
            "target_id": str(earning.id),
            "row_version": earning.row_version,
            "effective_to": "2026-10-31",
        },
    )
    with pytest.raises(AppError) as e:
        approve_change_request(db, admin, cr.id)
    assert e.value.code == "locked_period_affects"


def test_earning_deactivate_existing_overlaps_blocks(db, admin):
    emp = _mk_employee(db)
    _mk_locked_period(db, start=date(2026, 11, 1), end=date(2026, 11, 30))
    et = _mk_earning_type(db)
    earning = _mk_earning(
        db, emp, et, effective_from=date(2026, 1, 1), effective_to=None,
    )
    cr = _mk_cr(
        db, kind="employee_earning_deactivate", employee_id=emp.id,
        payload={"target_id": str(earning.id), "row_version": earning.row_version},
    )
    with pytest.raises(AppError) as e:
        approve_change_request(db, admin, cr.id)
    assert e.value.code == "locked_period_affects"


def test_employee_field_update_with_locked_payslip_blocks(db, admin):
    emp = _mk_employee(db)
    period = _mk_locked_period(db, start=date(2026, 11, 1), end=date(2026, 11, 30))
    _mk_locked_payslip(db, emp, period)
    cr = _mk_cr(
        db, kind="employee_field_update", employee_id=emp.id,
        payload={"row_version": emp.row_version, "uif_exempt": True},
    )
    with pytest.raises(AppError) as e:
        approve_change_request(db, admin, cr.id)
    assert e.value.code == "locked_period_affects"


def test_earning_create_future_allows(db, admin):
    emp = _mk_employee(db)
    _mk_locked_period(db, start=date(2026, 11, 1), end=date(2026, 11, 30))
    et = _mk_earning_type(db)
    cr = _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "500.00",
            "effective_from": "2026-12-01",
        },
    )
    row, applied_id = approve_change_request(db, admin, cr.id)
    assert row.status == "approved"
    persisted = db.scalar(
        select(EmployeeEarning).where(EmployeeEarning.id == applied_id)
    )
    assert persisted is not None


def test_earning_create_ended_before_locked_allows(db, admin):
    emp = _mk_employee(db)
    _mk_locked_period(db, start=date(2026, 11, 1), end=date(2026, 11, 30))
    et = _mk_earning_type(db)
    cr = _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "500.00",
            "effective_from": "2026-01-01",
            "effective_to": "2026-10-31",
        },
    )
    row, _applied_id = approve_change_request(db, admin, cr.id)
    assert row.status == "approved"


def test_employee_field_update_without_locked_payslip_allows(db, admin):
    emp = _mk_employee(db)
    _mk_locked_period(db, start=date(2026, 11, 1), end=date(2026, 11, 30))
    cr = _mk_cr(
        db, kind="employee_field_update", employee_id=emp.id,
        payload={"row_version": emp.row_version, "uif_exempt": True},
    )
    row, _applied_id = approve_change_request(db, admin, cr.id)
    assert row.status == "approved"
    db.refresh(emp)
    assert emp.uif_exempt is True


# ===========================================================================
# Stage 2b — salary-assignment approval guard
# ===========================================================================


def test_assignment_approve_effective_before_locked_blocks(db, admin):
    """effective_from BEFORE a locked period, but locked.end_date >=
    effective_from → block.

    This is the case my guard exists for: validate_date_rules likely blocks
    'effective_from within a locked period', but 'effective_from before a
    locked period' passes validate_date_rules while still affecting the
    locked period's payslips on recompute (new open-ended rows land inside
    the locked period's window; closes at effective_from - 1 also affect
    later locked periods).

    Distinct submitter/approver users are required because
    approve_assignment refuses self-approval.
    """
    d0 = date.today()
    effective_from = _mk_valid_base_period(db)   # d0 + 17
    # Future locked period starting AFTER effective_from; end_date > effective_from
    locked = _mk_locked_period(
        db,
        start=d0 + timedelta(days=40),
        end=d0 + timedelta(days=60),
    )
    emp = _mk_employee(db, pay_basis="monthly")
    structure = _mk_structure(db, admin)
    submitter = _mk_submitter(db)
    a = _submit_assignment(db, submitter, emp, structure, effective_from)
    with pytest.raises(AppError) as e:
        approve_assignment(db, admin, a.id)
    assert e.value.code == "locked_period_affects"
    assert e.value.details["period_id"] == str(locked.id)
    assert e.value.details["assignment_id"] == str(a.id)
    assert e.value.details["effective_from"] == effective_from.isoformat()


def test_assignment_approve_locked_ended_before_allows(db, admin):
    """locked.end_date < effective_from → allow."""
    d0 = date.today()
    effective_from = _mk_valid_base_period(db)   # d0 + 17
    _mk_locked_period(
        db,
        start=d0 - timedelta(days=30),
        end=d0 - timedelta(days=10),
    )
    emp = _mk_employee(db, pay_basis="monthly")
    structure = _mk_structure(db, admin)
    submitter = _mk_submitter(db)
    a = _submit_assignment(db, submitter, emp, structure, effective_from)
    result = approve_assignment(db, admin, a.id)
    assert result.status == "approved"


def test_assignment_approve_no_locked_periods_allows(db, admin):
    """No locked periods exist → allow."""
    effective_from = _mk_valid_base_period(db)   # d0 + 17
    emp = _mk_employee(db, pay_basis="monthly")
    structure = _mk_structure(db, admin)
    submitter = _mk_submitter(db)
    a = _submit_assignment(db, submitter, emp, structure, effective_from)
    result = approve_assignment(db, admin, a.id)
    assert result.status == "approved"