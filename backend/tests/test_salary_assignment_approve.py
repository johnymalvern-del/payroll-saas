"""Stage D — approve flow tests.

approve_assignment commits internally (design §5.12 Phase D). The
commit_as_flush fixture monkeypatches Session.commit to Session.flush so
the test runs inside _leave_session_shared's rolled-back transaction
without leaking data. Production semantics unchanged.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.pay import (
    EarningType, DeductionType, EmployeeDeduction, EmployeeEarning, PayPeriod,
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
    """Per-test session with commit redirected to flush."""
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


def _mk_period(db, *, start, end, pay_date, status="closed"):
    p = PayPeriod(
        id=uuid.uuid4(), period_key=f"P{uuid.uuid4().hex[:6]}",
        start_date=start, end_date=end, pay_date=pay_date,
        status=status, cutoff_at=__import__("datetime").datetime.utcnow(),
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
    code = f"ET{uuid.uuid4().hex[:8]}"
    et = EarningType(
        name="Bonus", code=code,
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


def _submit_and_approve(db, user, approver, emp, structure, effective_from,
                        overrides=None):
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=structure.id,
        effective_from=effective_from, idempotency_key=None,
        override_manual_ids=overrides or [],
    )
    return approve_assignment(db, approver, a.id)


# ----------------------------- tests -----------------------------

def test_approve_monthly_happy_path(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    assert a.status == "approved"
    assert a.decided_by_user_id == approver.id
    rows = db.scalars(select(EmployeeEarning).where(
        EmployeeEarning.employee_id == emp.id,
        EmployeeEarning.source_assignment_id == a.id,
    )).all()
    assert len(rows) == 1
    assert rows[0].amount == Decimal("15000")
    et = db.scalar(select(EarningType).where(EarningType.id == rows[0].earning_type_id))
    assert et.code == "BASE_MONTHLY"


def test_approve_hourly_inserts_pay_history_and_syncs_base_rate(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db, pay_basis="hourly")
    s = _mk_structure(db, user=user, pay_basis="hourly", base_rate="150.00")
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    assert a.status == "approved"
    ph = db.scalar(select(EmployeePayHistory).where(
        EmployeePayHistory.source_assignment_id == a.id,
    ))
    assert ph is not None
    assert ph.status == "approved"
    assert ph.source == "structure_assignment"
    assert ph.base_rate == Decimal("150.00")
    # No BASE_MONTHLY row should exist
    earnings = db.scalars(select(EmployeeEarning).where(
        EmployeeEarning.employee_id == emp.id,
    )).all()
    assert len(earnings) == 0


def test_approve_monthly_inserts_base_monthly_exactly_once(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    rows = db.scalars(select(EmployeeEarning).where(
        EmployeeEarning.employee_id == emp.id,
        EmployeeEarning.earning_type_id == db.scalar(
            select(EarningType.id).where(EarningType.code == "BASE_MONTHLY")
        ),
    )).all()
    assert len(rows) == 1


def test_approve_inserts_each_component_exactly_once(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    et = _mk_earning_type(db); dt = _mk_deduction_type(db)
    s = _mk_structure(db, user=user, components=[
        {"kind": "earning", "earning_type_id": et.id,
         "deduction_type_id": None, "amount": Decimal("500"), "rate": None},
        {"kind": "deduction", "earning_type_id": None,
         "deduction_type_id": dt.id, "amount": Decimal("200"), "rate": None},
    ])
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    earnings = db.scalars(select(EmployeeEarning).where(
        EmployeeEarning.employee_id == emp.id,
        EmployeeEarning.source_assignment_id == a.id,
        EmployeeEarning.earning_type_id == et.id,
    )).all()
    assert len(earnings) == 1
    deductions = db.scalars(select(EmployeeDeduction).where(
        EmployeeDeduction.employee_id == emp.id,
        EmployeeDeduction.source_assignment_id == a.id,
    )).all()
    assert len(deductions) == 1
    assert deductions[0].amount == Decimal("200")
    assert deductions[0].balance == Decimal("0")


def test_approve_closes_manual_override_rows(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    s = _mk_structure(db, user=user, components=[
        {"kind": "earning", "earning_type_id": et.id,
         "deduction_type_id": None, "amount": Decimal("500"), "rate": None},
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
    a = _submit_and_approve(
        db, user, approver, emp, s, d,
        overrides=[{"kind": "employee_earning", "id": me_id}],
    )
    closed = db.get(EmployeeEarning, me_id)
    assert closed.effective_to == d - timedelta(days=1)
    assert closed.is_active is True


def test_approve_closes_prior_structure_owned_rows(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    s1 = _mk_structure(db, user=user, base_rate="15000")
    d1 = _mk_valid_env(db)
    a1 = _submit_and_approve(db, user, approver, emp, s1, d1)
    first_row = db.scalar(select(EmployeeEarning).where(
        EmployeeEarning.source_assignment_id == a1.id,
    ))
    assert first_row is not None
    first_id = first_row.id

    # Submit second assignment with a later effective date
    d2 = d1 + timedelta(days=30)
    _mk_period(db, start=d2 - timedelta(days=7),
                end=d2 - timedelta(days=1),
                pay_date=d2)
    s2 = _mk_structure(db, user=user, base_rate="18000")
    a2 = _submit_and_approve(db, user, approver, emp, s2, d2)
    # The first assignment's row is closed
    old = db.get(EmployeeEarning, first_id)
    assert old.effective_to == d2 - timedelta(days=1)


def test_approve_updates_prior_assignment_effective_to(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    s1 = _mk_structure(db, user=user, base_rate="15000")
    d1 = _mk_valid_env(db)
    a1 = _submit_and_approve(db, user, approver, emp, s1, d1)
    d2 = d1 + timedelta(days=30)
    _mk_period(db, start=d2 - timedelta(days=7),
                end=d2 - timedelta(days=1), pay_date=d2)
    s2 = _mk_structure(db, user=user, base_rate="18000")
    a2 = _submit_and_approve(db, user, approver, emp, s2, d2)
    prev = db.get(EmployeeSalaryStructureAssignment, a1.id)
    assert prev.effective_to == d2 - timedelta(days=1)


def test_approve_refuses_self_approval(db):
    user = _mk_user(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )
    with pytest.raises(AppError) as exc:
        approve_assignment(db, user, a.id)
    assert exc.value.code == "self_approval_forbidden"


def test_approve_refuses_non_pending(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    with pytest.raises(AppError) as exc:
        approve_assignment(db, approver, a.id)
    assert exc.value.code == "not_pending"


def test_approve_creates_approved_attempt_row(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    attempts = db.scalars(select(EmployeeSalaryStructureAssignmentAttempt).where(
        EmployeeSalaryStructureAssignmentAttempt.assignment_id == a.id,
    )).all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "approved"
    assert attempts[0].failure_detail is None


def test_approve_pay_basis_mismatch_at_approve(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db, pay_basis="monthly")
    s = _mk_structure(db, user=user, pay_basis="monthly")
    d = _mk_valid_env(db)
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )
    # Mutate employee pay_basis between submit and approve
    emp.pay_basis = "hourly"
    db.flush()
    with pytest.raises(AppError) as exc:
        approve_assignment(db, approver, a.id)
    assert exc.value.code == "pay_basis_mismatch"


def test_approve_structure_inactive_at_approve(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )
    s.is_active = False
    db.flush()
    with pytest.raises(AppError) as exc:
        approve_assignment(db, approver, a.id)
    assert exc.value.code == "structure_inactive"


def test_approve_refuses_overlapping_rate_for_hourly(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db, pay_basis="hourly")
    s = _mk_structure(db, user=user, pay_basis="hourly", base_rate="150.00")
    d = _mk_valid_env(db)
    # Pre-existing approved pay history at same effective date
    ph = EmployeePayHistory(
        employee_id=emp.id, base_rate=Decimal("140.00"),
        effective_from=d, status="approved", source="individual",
        changed_by=user.id, approved_by=user.id, decided_by=user.id,
        decided_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(ph); db.flush()
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )
    with pytest.raises(AppError) as exc:
        approve_assignment(db, approver, a.id)
    assert exc.value.code == "overlapping_rate_effective_date"


def test_approve_refuses_effective_date_not_after_latest(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    s1 = _mk_structure(db, user=user)
    d1 = _mk_valid_env(db)
    a1 = _submit_and_approve(db, user, approver, emp, s1, d1)
    # Second assignment with earlier effective date: should be blocked
    s2 = _mk_structure(db, user=user)
    earlier = d1 - timedelta(days=1)
    a2 = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s2.id,
        effective_from=d1,  # same as latest
        idempotency_key=None, override_manual_ids=[],
    )
    with pytest.raises(AppError) as exc:
        approve_assignment(db, approver, a2.id)
    assert exc.value.code == "assignment_effective_date_not_after_latest_approved"


def test_approve_recheck_catches_new_manual_collision(db):
    """A manual row created between submit and approve is caught."""
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    s = _mk_structure(db, user=user, components=[
        {"kind": "earning", "earning_type_id": et.id,
         "deduction_type_id": None, "amount": Decimal("500"), "rate": None},
    ])
    d = _mk_valid_env(db)
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=s.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )
    # Insert a colliding manual row AFTER submit
    me = EmployeeEarning(
        employee_id=emp.id, earning_type_id=et.id,
        amount=Decimal("300"),
        effective_from=d - timedelta(days=30),
        effective_to=None, is_active=True, row_version=1,
    )
    db.add(me); db.flush()
    with pytest.raises(AppError) as exc:
        approve_assignment(db, approver, a.id)
    assert exc.value.code == "manual_component_type_collision"


def test_approve_recheck_catches_removed_override(db):
    """A manual row closed between submit and approve triggers close_set_mismatch."""
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    s = _mk_structure(db, user=user, components=[
        {"kind": "earning", "earning_type_id": et.id,
         "deduction_type_id": None, "amount": Decimal("500"), "rate": None},
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
    # Close the manual row before approve
    row = db.get(EmployeeEarning, me_id)
    row.is_active = False
    db.flush()
    with pytest.raises(AppError) as exc:
        approve_assignment(db, approver, a.id)
    assert exc.value.code == "close_set_mismatch"


def test_approve_creates_child_change_requests(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    s = _mk_structure(db, user=user, components=[
        {"kind": "earning", "earning_type_id": et.id,
         "deduction_type_id": None, "amount": Decimal("500"), "rate": None},
    ])
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    children = db.scalars(select(PayrollChangeRequest).where(
        PayrollChangeRequest.assignment_id == a.id,
    )).all()
    # At least one child: BASE_MONTHLY + one explicit earning
    assert len(children) >= 2
    for c in children:
        assert c.status == "approved"
        assert c.applied_entity_id is not None

# END OF FILE