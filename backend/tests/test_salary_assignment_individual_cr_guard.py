"""Stage C — individual-CR endpoints must refuse assignment children."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.people import Employee, User
from app.db.tenant.models.salary_structure import (
    EmployeeSalaryStructureAssignment,
    SalaryStructure,
)
from app.services.payroll_change_request import (
    approve_change_request,
    cancel_change_request,
    reject_change_request,
)


def _mk_user(db):
    return db.query(User).filter(User.username == "admin").one()


def _mk_other_user(db):
    """Insert a real second user (satisfies FK on requested_by_user_id)."""
    other = User(
        username=f"other_{uuid.uuid4().hex[:8]}",
        password_hash="x",
        role="hr",
        is_active=True,
        must_change_password=False,
        failed_attempts=0,
        row_version=1,
    )
    db.add(other)
    db.flush()
    return other


def _mk_employee(db):
    emp = Employee(
        employee_code=f"E{uuid.uuid4().hex[:8]}",
        first_name="T", last_name="E",
        hire_date=date.today() - timedelta(days=365),
        employee_type="monthly", pay_basis="monthly",
        pay_frequency="monthly", overtime_eligible=True,
        clocks=True, uif_exempt=False,
        medical_aid_dependants=0, medical_scheme_members=0,
        row_version=1,
    )
    db.add(emp)
    db.flush()
    return emp


def _mk_assignment_row(db, *, emp):
    """Insert a minimal real assignment row (satisfies FK on assignment_id)."""
    s = SalaryStructure(
        structure_group_id=uuid.uuid4(),
        version_number=1, is_current=True,
        name=f"GuardTest-{uuid.uuid4().hex[:6]}",
        description=None,
        pay_basis="monthly",
        base_rate=Decimal("10000"),
        is_active=True,
        row_version=1,
    )
    db.add(s)
    db.flush()
    a = EmployeeSalaryStructureAssignment(
        employee_id=emp.id,
        structure_id=s.id,
        effective_from=date.today() + timedelta(days=10),
        status="pending",
        override_manual_ids=[],
    )
    db.add(a)
    db.flush()
    return a


def _mk_assignment_child(db, *, emp, user, assignment):
    """Create a PayrollChangeRequest pointing at a real assignment."""
    child = PayrollChangeRequest(
        id=uuid.uuid4(),
        kind="employee_earning_create",
        employee_id=emp.id,
        payload={
            "earning_type_id": str(uuid.uuid4()),
            "amount": "100",
            "effective_from": date.today().isoformat(),
        },
        status="pending",
        requested_by_user_id=user.id,
        assignment_id=assignment.id,
    )
    db.add(child)
    db.flush()
    return child


def test_individual_approve_refuses_assignment_child(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    assignment = _mk_assignment_row(db, emp=emp)
    child = _mk_assignment_child(db, emp=emp, user=user, assignment=assignment)
    with pytest.raises(AppError) as exc:
        approve_change_request(db, user, child.id)
    assert exc.value.code == "assignment_requires_batch_approve"


def test_individual_reject_refuses_assignment_child(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    assignment = _mk_assignment_row(db, emp=emp)
    child = _mk_assignment_child(db, emp=emp, user=user, assignment=assignment)
    with pytest.raises(AppError) as exc:
        reject_change_request(db, user, child.id, "nope")
    assert exc.value.code == "assignment_requires_batch_reject"


def test_individual_cancel_refuses_assignment_child(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    assignment = _mk_assignment_row(db, emp=emp)
    child = _mk_assignment_child(db, emp=emp, user=user, assignment=assignment)
    with pytest.raises(AppError) as exc:
        cancel_change_request(db, user, child.id)
    assert exc.value.code == "assignment_requires_batch_cancel"


def test_individual_approve_still_works_for_non_assignment(_leave_session_shared):
    """Guard must not break the pre-existing individual CR flow."""
    from app.db.tenant.models.pay import EarningType
    db = _leave_session_shared
    user = _mk_user(db)
    other_user = _mk_other_user(db)
    emp = _mk_employee(db)
    et = EarningType(
        name="Bonus", code=f"B{uuid.uuid4().hex[:6]}",
        calc_method="fixed_amount", frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        proration_rule="none", is_system=False, is_active=True, row_version=1,
    )
    db.add(et)
    db.flush()
    # Different requester so self-approval guard doesn't fire; no assignment_id
    # so the assignment-child guard doesn't fire.
    cr = PayrollChangeRequest(
        id=uuid.uuid4(),
        kind="employee_earning_create",
        employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "500",
            "effective_from": date.today().isoformat(),
        },
        status="pending",
        requested_by_user_id=other_user.id,
    )
    db.add(cr)
    db.flush()
    approved, _applied = approve_change_request(db, user, cr.id)
    assert approved.status == "approved"
    assert approved.applied_entity_id is not None

# END OF FILE