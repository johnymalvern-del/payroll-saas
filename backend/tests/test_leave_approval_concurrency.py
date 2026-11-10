"""B-L4b: concurrency protection for decide_step / decide_shortcut.

Covers B-L4-3 — SELECT ... FOR UPDATE on LeaveApprovalStep to prevent
double-apply of side effects when two approvers act concurrently.

Also covers regression tests:
- Manager scope on decide (out-of-scope request → 404)
- IDOR safety (nonexistent request → 404)
- No double side-effects on refused second decision

Note: a true multi-threaded concurrency test is not included here — the
fixture infrastructure does not expose a thread-safe engine handle without
breaking the shared-session teardown. The two properties we can verify
deterministically cover the same invariant:
  (a) the runtime SQL emitted by _current_step contains FOR UPDATE
  (b) a refused second decision on the same step does not create any
      additional adjustments (no double-apply).
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import event, select

from app.api.v1.leave_requests import (
    _current_step,
    create_leave_request,
    decide_step,
    submit_leave_request,
)
from app.api.v1.leave_requests_schemas import (
    LeaveRequestIn,
    StepDecideIn,
)
from app.core.errors import AppError
from app.db.tenant.models.attendance import Adjustment
from app.db.tenant.models.leave import LeaveApprovalStep, LeaveRequest

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


# ── B-L4-3: FOR UPDATE lock present in SQL ──────────────────────────


def test_current_step_emits_for_update_sql(session):
    """B-L4-3: _current_step's emitted SQL must include FOR UPDATE."""
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, admin,
    )
    submit_leave_request(r.id, session, admin)

    req = session.get(LeaveRequest, r.id)
    assert req is not None

    captured: list[str] = []
    bind = session.get_bind()
    target = getattr(bind, "engine", bind)

    def _capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    event.listen(target, "before_cursor_execute", _capture)
    try:
        _current_step(session, req)
    finally:
        event.remove(target, "before_cursor_execute", _capture)

    step_sqls = [s for s in captured if "leave_approval_step" in s.lower()]
    assert step_sqls, f"No step queries captured: {captured}"
    assert any("FOR UPDATE" in s.upper() for s in step_sqls), (
        f"B-L4-3: expected FOR UPDATE in step query, got: {step_sqls}"
    )


# ── B-L4-3: no double-apply on refused second decision ──────────────


def test_second_decide_on_final_step_creates_no_extra_adjustments(session):
    """Two decisions on the same final step: only one applies side effects."""
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 2),
        ),
        session, admin,
    )
    submit_leave_request(r.id, session, admin)
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    assert step is not None

    # First decision: succeeds, applies side effects (one adjustment per day)
    decide_step(r.id, step.id, StepDecideIn(approve=True), session, hr_user)
    session.expire_all()
    after_first = list(session.scalars(select(Adjustment).where(
        Adjustment.leave_request_id == r.id,
        Adjustment.system_generated.is_(True),
    )).all())
    assert len(after_first) == 2, f"expected 2 adjustments, got {len(after_first)}"

    # Second decision on the same step: must be refused cleanly
    with pytest.raises(AppError) as e:
        decide_step(r.id, step.id, StepDecideIn(approve=True), session, hr_user)
    assert e.value.code in ("step_already_decided", "wrong_step")

    # No extra adjustments
    session.expire_all()
    after_second = list(session.scalars(select(Adjustment).where(
        Adjustment.leave_request_id == r.id,
        Adjustment.system_generated.is_(True),
    )).all())
    assert len(after_second) == 2, (
        f"double-apply detected: {len(after_second)} adjustments after refused second decision"
    )


# ── Regression: manager scope on decide ─────────────────────────────


def test_manager_cannot_decide_out_of_scope_request(session):
    """Manager (LEAVE_APPROVE, no EMPLOYEE_CRUD) cannot decide requests
    for employees outside their scope — scope failure → 404 (IDOR-safe)."""
    _mk_company(session)
    _mk_cal(session, 2026)
    # emp is not a direct report of mgr_user's employee
    emp = _mk_emp(session, code="E")
    mgr_emp = _mk_emp(session, code="MGR")
    mgr_user = _mk_user_for(session, mgr_emp, "manager")
    emp.manager_id = None
    session.flush()
    hr_emp = _mk_emp(session, code="HR")
    hr_user = _mk_user_for(session, hr_emp, "hr")
    t = _mk_type(session, approval_chain=["hr"])
    _mk_balance(session, emp, t)
    admin = _admin(session)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, admin,
    )
    submit_leave_request(r.id, session, admin)
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    assert step is not None

    with pytest.raises(AppError) as e:
        decide_step(r.id, step.id, StepDecideIn(approve=True), session, mgr_user)
    assert e.value.code == "not_found"


# ── Regression: IDOR / cross-tenant safety ──────────────────────────


def test_decide_nonexistent_request_returns_404(session):
    """Request IDs from another tenant or fabricated IDs → 404 (IDOR-safe)."""
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    fake_req_id = uuid.uuid4()
    fake_step_id = uuid.uuid4()
    with pytest.raises(AppError) as e:
        decide_step(fake_req_id, fake_step_id, StepDecideIn(approve=True), session, hr_user)
    assert e.value.code == "not_found"