"""M6 Stage A — change-request scope enforcement.

Verifies that list / get / approve / reject / cancel reject out-of-scope
requests with 404 (indistinguishable from nonexistent). Submission
scope (already present) is untouched.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.api.v1.payroll_change_requests import get_request, list_requests
from app.core.errors import AppError
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.organisation import Branch
from app.db.tenant.models.people import Employee, User, UserScope
from app.services.payroll_change_request import (
    approve_change_request,
    cancel_change_request,
    reject_change_request,
)


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


def _mk_employee(session, code, branch_id):
    _mk_branch(session, branch_id)  # ensure FK target exists first
    emp = Employee(
        employee_code=code,
        first_name="Test",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status="active",
        pay_basis="hourly",
        pay_frequency="monthly",
        branch_id=branch_id,
        row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


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


def _mk_cr(session, employee_id, requester_user_id=None):
    cr = PayrollChangeRequest(
        id=uuid.uuid4(),
        kind="employee_earning_create",
        employee_id=employee_id,
        payload={
            "earning_type_id": str(uuid.uuid4()),
            "amount": "1000.00",
            "effective_from": "2026-01-01",
        },
        status="pending",
        requested_by_user_id=requester_user_id,
        assignment_id=None,
        row_version=1,
    )
    session.add(cr)
    session.flush()
    return cr


# 1 — list filtered by scope
def test_hr_branch_a_list_excludes_branch_b(session):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    cr_a = _mk_cr(session, emp_a.id)
    cr_b = _mk_cr(session, emp_b.id)
    hr_a = _mk_user(session, "hr")
    _mk_scope(session, hr_a, "branch", branch_a)
    out = list_requests(
        session, hr_a, status=None, employee_id=None, limit=100, cursor=None,
    )
    ids = {r.id for r in out.items}
    assert cr_a.id in ids
    assert cr_b.id not in ids


# 2 — individual retrieval 404 for out-of-scope
def test_hr_branch_a_get_branch_b_returns_404(session):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    emp_b = _mk_employee(session, "EB", branch_b)
    cr_b = _mk_cr(session, emp_b.id)
    hr_a = _mk_user(session, "hr")
    _mk_scope(session, hr_a, "branch", branch_a)
    with pytest.raises(AppError) as e:
        get_request(cr_b.id, session, hr_a)
    assert e.value.code == "not_found"


# 3 — cancel 404 for out-of-scope (scope fires before requester check)
def test_hr_branch_a_cancel_branch_b_returns_404(session):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    emp_b = _mk_employee(session, "EB", branch_b)
    hr_a = _mk_user(session, "hr")
    _mk_scope(session, hr_a, "branch", branch_a)
    cr_b = _mk_cr(session, emp_b.id, requester_user_id=hr_a.id)
    with pytest.raises(AppError) as e:
        cancel_change_request(session, hr_a, cr_b.id)
    assert e.value.code == "not_found"


# 4 — cancel in-scope requester still succeeds
def test_hr_branch_a_cancel_own_branch_a_succeeds(session):
    branch_a = uuid.uuid4()
    emp_a = _mk_employee(session, "EA", branch_a)
    hr_a = _mk_user(session, "hr")
    _mk_scope(session, hr_a, "branch", branch_a)
    cr_a = _mk_cr(session, emp_a.id, requester_user_id=hr_a.id)
    result = cancel_change_request(session, hr_a, cr_a.id)
    assert result.status == "cancelled"


# 5 — scoped approver cannot approve out-of-scope
def test_scoped_approver_cannot_approve_out_of_scope(session):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    emp_b = _mk_employee(session, "EB", branch_b)
    cr_b = _mk_cr(session, emp_b.id)
    approver = _mk_user(session, "hr")
    _mk_scope(session, approver, "branch", branch_a)
    with pytest.raises(AppError) as e:
        approve_change_request(session, approver, cr_b.id)
    assert e.value.code == "not_found"


# 6 — payroll_admin sees all (regression)
def test_payroll_admin_list_returns_all(session):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    cr_a = _mk_cr(session, emp_a.id)
    cr_b = _mk_cr(session, emp_b.id)
    admin = _mk_user(session, "payroll_admin")
    out = list_requests(
        session, admin, status=None, employee_id=None, limit=100, cursor=None,
    )
    ids = {r.id for r in out.items}
    assert cr_a.id in ids
    assert cr_b.id in ids


# 7 — HR without scope rows: fail-open preserved
def test_hr_no_scope_rows_returns_all(session):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    emp_a = _mk_employee(session, "EA", branch_a)
    emp_b = _mk_employee(session, "EB", branch_b)
    cr_a = _mk_cr(session, emp_a.id)
    cr_b = _mk_cr(session, emp_b.id)
    hr = _mk_user(session, "hr")
    out = list_requests(
        session, hr, status=None, employee_id=None, limit=100, cursor=None,
    )
    ids = {r.id for r in out.items}
    assert cr_a.id in ids
    assert cr_b.id in ids


# 8 — reject 404 for out-of-scope
def test_hr_branch_a_reject_branch_b_returns_404(session):
    branch_a, branch_b = uuid.uuid4(), uuid.uuid4()
    emp_b = _mk_employee(session, "EB", branch_b)
    cr_b = _mk_cr(session, emp_b.id)
    approver = _mk_user(session, "hr")
    _mk_scope(session, approver, "branch", branch_a)
    with pytest.raises(AppError) as e:
        reject_change_request(session, approver, cr_b.id, note="rejected")
    assert e.value.code == "not_found"