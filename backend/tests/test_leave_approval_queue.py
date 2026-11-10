"""B-L4a: approval queue filter + LeaveRequestOut display fields.

Covers B-L4-1 (awaiting_approver_user_id) and B-L4-2
(employee_code / employee_name / leave_type_name).

Reuses helpers from test_leave_approval.py — no fixture duplication.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.api.v1.leave_requests import (
    _to_out,
    create_leave_request,
    decide_step,
    get_leave_request,
    list_leave_requests,
    submit_leave_request,
)
from app.api.v1.leave_requests_schemas import (
    LeaveRequestIn,
    StepDecideIn,
)
from app.core.errors import AppError
from app.db.tenant.models.leave import LeaveApprovalStep, LeaveRequest
from app.db.tenant.models.people import UserScope

try:
    from test_leave_approval import (
        _admin,
        _mk_balance,
        _mk_cal,
        _mk_emp,
        _mk_type,
        _mk_user_for,
        _setup_two_approvers,
    )
except ImportError:
    from tests.test_leave_approval import (
        _admin,
        _mk_balance,
        _mk_cal,
        _mk_emp,
        _mk_type,
        _mk_user_for,
        _setup_two_approvers,
    )

try:
    from test_payroll_attendance_earnings import _mk_company
except ImportError:
    from tests.test_payroll_attendance_earnings import _mk_company


@pytest.fixture()
def session(_leave_session_shared):
    return _leave_session_shared


def _submit_one(session, admin, emp, t, *, day=1) -> uuid.UUID:
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, day), to_date=date(2026, 6, day),
        ),
        session, admin,
    )
    submit_leave_request(r.id, session, admin)
    return r.id


# ── B-L4-1: queue filter ─────────────────────────────────────────────


def test_queue_returns_request_for_assigned_approver(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    rid = _submit_one(session, admin, emp, t)
    out = list_leave_requests(
        session, hr_user,
        awaiting_approver_user_id=hr_user.id,
    )
    assert any(item.id == rid for item in out.items)


def test_queue_other_user_id_forbidden(session):
    _mk_company(session)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    with pytest.raises(AppError) as e:
        list_leave_requests(
            session, hr_user,
            awaiting_approver_user_id=admin.id,
        )
    assert e.value.code == "awaiting_filter_not_self"


def test_queue_employee_user_forbidden(session):
    _mk_company(session)
    emp = _mk_emp(session)
    emp_user = _mk_user_for(session, emp, "employee")
    with pytest.raises(AppError) as e:
        list_leave_requests(
            session, emp_user,
            awaiting_approver_user_id=emp_user.id,
        )
    assert e.value.code == "forbidden"


def test_queue_excludes_request_for_other_approver(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    rid = _submit_one(session, admin, emp, t)
    out = list_leave_requests(
        session, admin,
        awaiting_approver_user_id=admin.id,
    )
    assert all(item.id != rid for item in out.items)


def test_queue_excludes_approved_request(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    rid = _submit_one(session, admin, emp, t)
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == rid,
        LeaveApprovalStep.status == "pending",
    ))
    decide_step(rid, step.id, StepDecideIn(approve=True), session, hr_user)
    out = list_leave_requests(
        session, hr_user,
        awaiting_approver_user_id=hr_user.id,
    )
    assert all(item.id != rid for item in out.items)


def test_queue_excludes_when_earlier_step_pending(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp = _mk_emp(session)
    mgr_emp = _mk_emp(session, code="MGR")
    mgr_user = _mk_user_for(session, mgr_emp, "manager")
    hr_emp = _mk_emp(session, code="HR")
    hr_user = _mk_user_for(session, hr_emp, "hr")
    emp.manager_id = mgr_emp.id
    session.flush()
    t = _mk_type(session, approval_chain=["manager", "hr"])
    _mk_balance(session, emp, t)
    admin = _admin(session)
    rid = _submit_one(session, admin, emp, t)

    hr_out = list_leave_requests(
        session, hr_user, awaiting_approver_user_id=hr_user.id,
    )
    assert all(item.id != rid for item in hr_out.items)

    mgr_out = list_leave_requests(
        session, mgr_user, awaiting_approver_user_id=mgr_user.id,
    )
    assert any(item.id == rid for item in mgr_out.items)

    mgr_step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == rid,
        LeaveApprovalStep.step_no == 1,
    ))
    decide_step(rid, mgr_step.id, StepDecideIn(approve=True),
                session, mgr_user)

    hr_out_after = list_leave_requests(
        session, hr_user, awaiting_approver_user_id=hr_user.id,
    )
    assert any(item.id == rid for item in hr_out_after.items)


def test_queue_respects_scope_restriction(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    session.add(UserScope(
        user_id=hr_user.id,
        scope_type="site",
        scope_id=uuid.uuid4(),
    ))
    session.flush()
    rid = _submit_one(session, admin, emp, t)
    out = list_leave_requests(
        session, hr_user, awaiting_approver_user_id=hr_user.id,
    )
    assert all(item.id != rid for item in out.items)


def test_queue_composes_with_employee_filter(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp1, hr_user, admin, t = _setup_two_approvers(session)
    emp2 = _mk_emp(session, code="E2")
    _mk_balance(session, emp2, t)
    r1 = _submit_one(session, admin, emp1, t, day=1)
    r2 = _submit_one(session, admin, emp2, t, day=2)
    out = list_leave_requests(
        session, hr_user,
        awaiting_approver_user_id=hr_user.id,
        employee_id=emp1.id,
    )
    ids = {item.id for item in out.items}
    assert r1 in ids
    assert r2 not in ids


def test_queue_absent_preserves_behaviour(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    rid = _submit_one(session, admin, emp, t)
    out = list_leave_requests(session, admin)
    assert any(item.id == rid for item in out.items)


# ── B-L4-2: display fields ───────────────────────────────────────────


def test_list_includes_display_fields(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    rid = _submit_one(session, admin, emp, t)
    out = list_leave_requests(session, admin)
    item = next(i for i in out.items if i.id == rid)
    assert item.employee_code == emp.employee_code
    assert item.employee_name == f"{emp.first_name} {emp.last_name}"
    assert item.leave_type_name == t.name


def test_detail_includes_display_fields(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    rid = _submit_one(session, admin, emp, t)
    out = get_leave_request(rid, session, admin)
    assert out.employee_code == emp.employee_code
    assert out.employee_name == f"{emp.first_name} {emp.last_name}"
    assert out.leave_type_name == t.name


def test_to_out_with_missing_display_data_returns_none(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    rid = _submit_one(session, admin, emp, t)
    req_model = session.get(LeaveRequest, rid)
    out = _to_out(session, req_model, employee=None, leave_type=None)
    assert out.employee_code is None
    assert out.employee_name is None
    assert out.leave_type_name is None