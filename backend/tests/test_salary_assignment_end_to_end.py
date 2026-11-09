"""Stage E — end-to-end integration coverage for salary assignment.

Covers:
  * monthly happy path (BASE_MONTHLY + component rows + children + attempts)
  * hourly happy path (EmployeePayHistory row + base_rate sync)
  * manual override lifecycle (close, child creation, is_active unchanged)
  * retry after a failed batch (design §5.12 recovery path, append-only proof)
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.pay import (
    DeductionType, EarningType, EmployeeDeduction, EmployeeEarning, PayPeriod,
)
from app.db.tenant.models.people import Employee, EmployeePayHistory, User
from app.db.tenant.models.salary_structure import (
    EmployeeSalaryStructureAssignment,
    EmployeeSalaryStructureAssignmentAttempt,
)
from app.services.salary_assignment_approve_service import approve_assignment
from app.services.salary_assignment_service import submit_assignment
from app.services.salary_structure_service import create_structure


# ----------------------------- fixtures -----------------------------

@pytest.fixture()
def db(_leave_session_shared, monkeypatch):
    s = _leave_session_shared
    monkeypatch.setattr(s, "commit", lambda: s.flush())
    return s


# ----------------------------- helpers -----------------------------

def _mk_user(db):
    return db.query(User).filter(User.username == "admin").one()


def _mk_approver(db):
    u = User(
        username=f"appr_{uuid.uuid4().hex[:8]}",
        password_hash="x", role="payroll_admin",
        is_active=True, must_change_password=False,
        failed_attempts=0, row_version=1,
    )
    db.add(u); db.flush()
    return u


def _mk_employee(db, *, pay_basis="monthly"):
    emp = Employee(
        employee_code=f"E{uuid.uuid4().hex[:8]}",
        first_name="T", last_name="E",
        hire_date=date.today() - timedelta(days=365),
        employee_type="monthly" if pay_basis == "monthly" else "hourly",
        pay_basis=pay_basis, pay_frequency="monthly",
        overtime_eligible=True, clocks=True, uif_exempt=False,
        medical_aid_dependants=0, medical_scheme_members=0,
        row_version=1,
    )
    db.add(emp); db.flush()
    return emp


def _mk_period(db, *, start, end, pay_date):
    p = PayPeriod(
        id=uuid.uuid4(), period_key=f"P{uuid.uuid4().hex[:6]}",
        start_date=start, end_date=end, pay_date=pay_date,
        status="closed",
        cutoff_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(p); db.flush()
    return p


def _mk_valid_env(db):
    today = date.today()
    s = today + timedelta(days=10)
    e = s + timedelta(days=6)
    _mk_period(db, start=s, end=e, pay_date=e + timedelta(days=1))
    return e + timedelta(days=1)


def _mk_structure(db, *, user, pay_basis="monthly", base_rate="15000", components=None):
    return create_structure(
        db, user, name=f"S{uuid.uuid4().hex[:6]}",
        description=None, pay_basis=pay_basis,
        base_rate=Decimal(base_rate),
        components=components or [],
    )


def _mk_earning_type(db):
    et = EarningType(
        name="Bonus", code=f"ET{uuid.uuid4().hex[:8]}",
        calc_method="fixed_amount", frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        proration_rule="none", is_system=False, is_active=True, row_version=1,
    )
    db.add(et); db.flush()
    return et


def _mk_deduction_type(db):
    dt = DeductionType(
        name="Loan", code=f"DT{uuid.uuid4().hex[:8]}",
        category="other", priority=100, is_pre_tax=False,
        is_system=False, is_active=True, row_version=1,
    )
    db.add(dt); db.flush()
    return dt


# ----------------------------- tests -----------------------------

def test_full_flow_monthly_assignment(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    et = _mk_earning_type(db); dt = _mk_deduction_type(db)
    s = _mk_structure(db, user=user, base_rate="18000", components=[
        {"kind": "earning", "earning_type_id": et.id,
         "deduction_type_id": None, "amount": Decimal("750"), "rate": None},
        {"kind": "deduction", "earning_type_id": None,
         "deduction_type_id": dt.id, "amount": Decimal("400"), "rate": None},
    ])
    d = _mk_valid_env(db)
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )
    approved = approve_assignment(db, approver, a.id)

    assert approved.status == "approved"
    assert approved.decided_by_user_id == approver.id

    # BASE_MONTHLY + the explicit earning component; one deduction
    base_et = db.scalar(select(EarningType).where(
        EarningType.code == "BASE_MONTHLY"))
    base_row = db.scalar(select(EmployeeEarning).where(
        EmployeeEarning.employee_id == emp.id,
        EmployeeEarning.source_assignment_id == a.id,
        EmployeeEarning.earning_type_id == base_et.id,
    ))
    assert base_row is not None
    assert base_row.amount == Decimal("18000")
    assert base_row.rate is None

    explicit_earn = db.scalar(select(EmployeeEarning).where(
        EmployeeEarning.employee_id == emp.id,
        EmployeeEarning.source_assignment_id == a.id,
        EmployeeEarning.earning_type_id == et.id,
    ))
    assert explicit_earn is not None
    assert explicit_earn.amount == Decimal("750")

    deduction = db.scalar(select(EmployeeDeduction).where(
        EmployeeDeduction.employee_id == emp.id,
        EmployeeDeduction.source_assignment_id == a.id,
    ))
    assert deduction is not None
    assert deduction.amount == Decimal("400")
    assert deduction.balance == Decimal("0")

    children = db.scalars(select(PayrollChangeRequest).where(
        PayrollChangeRequest.assignment_id == a.id,
    )).all()
    kinds = sorted(c.kind for c in children)
    assert "employee_earning_create" in kinds
    assert "employee_deduction_create" in kinds
    for c in children:
        assert c.status == "approved"
        assert c.applied_entity_id is not None

    attempts = db.scalars(select(EmployeeSalaryStructureAssignmentAttempt).where(
        EmployeeSalaryStructureAssignmentAttempt.assignment_id == a.id,
    )).all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "approved"


def test_full_flow_hourly_assignment(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db, pay_basis="hourly")
    s = _mk_structure(db, user=user, pay_basis="hourly", base_rate="175.50")
    d = _mk_valid_env(db)
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )
    approve_assignment(db, approver, a.id)

    ph = db.scalar(select(EmployeePayHistory).where(
        EmployeePayHistory.source_assignment_id == a.id,
    ))
    assert ph is not None
    assert ph.status == "approved"
    assert ph.source == "structure_assignment"
    assert ph.base_rate == Decimal("175.50")
    assert ph.effective_from == d
    assert ph.decided_by == approver.id

    # No BASE_MONTHLY row for hourly employees
    earnings = db.scalars(select(EmployeeEarning).where(
        EmployeeEarning.employee_id == emp.id,
    )).all()
    assert len(earnings) == 0

    # No child CR for the hourly rate (design §5.10 / L12)
    children = db.scalars(select(PayrollChangeRequest).where(
        PayrollChangeRequest.assignment_id == a.id,
    )).all()
    assert len(children) == 0


def test_manual_override_full_lifecycle(db):
    """Manual row exists → user selects it as override → approve closes it
    via effective_to, leaves is_active=True, and creates a deactivate child."""
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    s = _mk_structure(db, user=user, components=[
        {"kind": "earning", "earning_type_id": et.id,
         "deduction_type_id": None, "amount": Decimal("800"), "rate": None},
    ])
    d = _mk_valid_env(db)
    me = EmployeeEarning(
        employee_id=emp.id, earning_type_id=et.id,
        amount=Decimal("300"),
        effective_from=d - timedelta(days=60),
        effective_to=None, is_active=True, row_version=1,
    )
    db.add(me); db.flush()
    me_id = me.id

    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None,
        override_manual_ids=[{"kind": "employee_earning", "id": me_id}],
    )
    approve_assignment(db, approver, a.id)

    closed = db.get(EmployeeEarning, me_id)
    assert closed.effective_to == d - timedelta(days=1)
    assert closed.is_active is True
    assert closed.source_assignment_id is None
    assert closed.effective_from == d - timedelta(days=60)  # unchanged

    # Closure child exists with the right shape
    child = db.scalar(select(PayrollChangeRequest).where(
        PayrollChangeRequest.assignment_id == a.id,
        PayrollChangeRequest.kind == "employee_earning_deactivate",
    ))
    assert child is not None
    assert child.status == "approved"
    assert child.applied_entity_id == me_id
    assert child.payload["reason"] == "structure_overridden"


def test_retry_after_failed_attempt_leaves_first_unchanged(db, monkeypatch):
    """Design §5.12 recovery + §5.8 append-only.

    A batch IntegrityError is simulated to force the recovery helper to record
    a failed attempt, then the failure cause is removed and the retry
    succeeds. Both attempt rows must exist; the first must be byte-identical.
    """
    from app.services import salary_assignment_approve_service as svc_mod

    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )

    # Force batch failure on the first approve.
    original_insert = svc_mod._insert_monthly_base

    def boom(*args, **kwargs):
        raise IntegrityError("simulated", {}, Exception("test-forced"))

    monkeypatch.setattr(svc_mod, "_insert_monthly_base", boom)

    # No-op the outer rollback so test setup survives. The batch savepoint's
    # own rollback (sp.rollback()) still works and discards partial rows.
    original_rollback = db.rollback
    monkeypatch.setattr(db, "rollback", lambda: None)

    with pytest.raises(AppError) as exc:
        approve_assignment(db, approver, a.id)
    assert exc.value.code == "approval_batch_failed"

    # First attempt recorded as failed
    attempts = db.scalars(select(EmployeeSalaryStructureAssignmentAttempt).where(
        EmployeeSalaryStructureAssignmentAttempt.assignment_id == a.id,
    )).all()
    assert len(attempts) == 1
    first = attempts[0]
    assert first.outcome == "failed"
    assert first.failure_detail is not None
    assert first.failure_detail.startswith("integrity_violation:")
    first_id = first.id
    first_time = first.attempted_at
    first_detail = first.failure_detail

    # Assignment still pending, retryable
    db.refresh(a)
    assert a.status == "pending"

    # Restore and retry
    monkeypatch.setattr(svc_mod, "_insert_monthly_base", original_insert)
    monkeypatch.setattr(db, "rollback", original_rollback)

    approved = approve_assignment(db, approver, a.id)
    assert approved.status == "approved"

    # Two attempts; first is unchanged
    attempts = db.scalars(select(EmployeeSalaryStructureAssignmentAttempt).where(
        EmployeeSalaryStructureAssignmentAttempt.assignment_id == a.id,
    ).order_by(EmployeeSalaryStructureAssignmentAttempt.attempted_at.asc())).all()
    assert len(attempts) == 2
    refreshed_first = db.get(EmployeeSalaryStructureAssignmentAttempt, first_id)
    assert refreshed_first.outcome == "failed"
    assert refreshed_first.attempted_at == first_time
    assert refreshed_first.failure_detail == first_detail
    second = [at for at in attempts if at.id != first_id][0]
    assert second.outcome == "approved"
    assert second.failure_detail is None

# END OF FILE