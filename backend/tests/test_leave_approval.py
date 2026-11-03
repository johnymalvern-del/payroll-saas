"""Chapter 3 L2d: approval chain decisions, capture-on-behalf, attendance."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.api.v1.leave_requests import (
    advance_request,
    create_leave_request,
    decide_shortcut,
    decide_step,
    submit_leave_request,
)
from app.api.v1.leave_requests_schemas import (
    DecideIn,
    LeaveRequestIn,
    StepDecideIn,
)
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.attendance import (
    Adjustment,
    AttendanceDay,
    EmployeeWorkPattern,
    ExceptionItem,
    WorkPattern,
    WorkPatternDay,
)
from app.db.tenant.models.leave import (
    LeaveApprovalStep,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, User
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


_TENANT_URL = (
    "postgresql+psycopg://payroll_app:payroll_app_dev_password"
    "@localhost:5432/{db}"
)


@dataclass
class _D:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_D]:
    slug = f"lapp-{uuid.uuid4().hex[:8]}"
    r = provision_tenant(
        slug=slug, name="LApp Co",
        admin_username="admin",
        admin_password_hash=hash_password("AdminPassword123!"),
    )
    try:
        yield _D(slug=slug, tenant_db_name=r.tenant_db_name, subscriber_id=r.subscriber_id)
    finally:
        _drop_tenant_database(r.tenant_db_name)
        with control_session() as s:
            x = s.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if x is not None:
                s.delete(x)


@pytest.fixture()
def session(_leave_session_shared):
    return _leave_session_shared


try:
    from test_payroll_attendance_earnings import _mk_company
except ImportError:
    from tests.test_payroll_attendance_earnings import _mk_company

def _admin(session) -> User:
    u = session.scalar(select(User).where(User.username == "admin"))
    assert u is not None
    return u


def _mk_cal(session, year):
    from app.db.tenant.models.attendance import CountryCalendar
    target = date(year, 12, 25)
    if session.scalar(select(CountryCalendar).where(
        CountryCalendar.country_code == "ZA",
        CountryCalendar.holiday_date == target,
    )) is None:
        session.add(CountryCalendar(
            country_code="ZA", holiday_date=target,
            name="Xmas", source_ref="test",
        ))
        session.flush()


def _mk_emp(session, code="E1", with_pattern=True) -> Employee:
    emp = Employee(
        employee_code=code, first_name="A", last_name="B",
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly",
        pay_frequency="monthly", row_version=1,
    )
    session.add(emp); session.flush()
    if with_pattern:
        wp = WorkPattern(
            name=f"wp-{code}", cycle_length_days=7,
            anchor_date=date(2024, 1, 1), is_active=True, row_version=1,
        )
        session.add(wp); session.flush()
        for i in range(7):
            session.add(WorkPatternDay(
                work_pattern_id=wp.id, day_index=i,
                is_expected=True, expected_shift_id=None,
            ))
        session.flush()
        emp.work_pattern_id = wp.id
        session.add(EmployeeWorkPattern(
            employee_id=emp.id, work_pattern_id=wp.id,
            effective_from=date(2024, 1, 1), effective_to=None,
        ))
        session.flush()
    return emp


def _mk_type(session, *, code="annual", approval_chain=None,
             requires_approval=True, allow_negative=False) -> LeaveType:
    t = LeaveType(
        name=f"T-{code}", code=code, unit="day", paid=True,
        accrual_method="annual", accrual_amount=Decimal("20"),
        cycle="calendar", requires_approval=requires_approval,
        allow_negative=allow_negative, max_carryover=None,
        approval_chain=list(approval_chain or ["hr"]),
        requires_payroll_admin_final=False,
        is_active=True, row_version=1,
    )
    session.add(t); session.flush()
    return t


def _mk_user_for(session, emp, role) -> User:
    u = User(
        username=f"{role}-{uuid.uuid4().hex[:6]}", password_hash="x",
        employee_id=emp.id, role=role, is_active=True,
        must_change_password=False, failed_attempts=0, row_version=1,
    )
    session.add(u); session.flush()
    return u


def _mk_balance(session, emp, t, accrued="20"):
    b = LeaveBalance(
        employee_id=emp.id, leave_type_id=t.id,
        cycle_start=date(2026, 1, 1), cycle_end=date(2026, 12, 31),
        entitled=Decimal("20"), accrued=Decimal(accrued),
        taken=Decimal("0"), pending=Decimal("0"),
        carried_in=Decimal("0"), adjusted=Decimal("0"),
        row_version=1,
    )
    session.add(b); session.flush()
    return b


def _setup_two_approvers(session, approval_chain=None):
    """Emp + hr user + payroll_admin user (admin)."""
    emp = _mk_emp(session)
    hr_emp = _mk_emp(session, code="HR")
    hr_user = _mk_user_for(session, hr_emp, "hr")
    t = _mk_type(session, approval_chain=approval_chain or ["hr"])
    _mk_balance(session, emp, t)
    admin = _admin(session)
    return emp, hr_user, admin, t


def test_approve_single_step_approves_and_adjusts(session):
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
    out = decide_step(
        r.id, step.id, StepDecideIn(approve=True),
        session, hr_user,
    )
    assert out.status == "approved"
    adjs = list(session.scalars(select(Adjustment).where(
        Adjustment.leave_request_id == r.id,
        Adjustment.system_generated.is_(True),
        Adjustment.outcome == "leave",
    )).all())
    assert len(adjs) == 2


def test_reject_step_releases_pending(session):
    emp, hr_user, admin, t = _setup_two_approvers(session)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 2),
        ),
        session, admin,
    )
    submit_leave_request(r.id, session, admin)
    bal = session.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == emp.id,
        LeaveBalance.leave_type_id == t.id,
    ))
    assert bal.pending == Decimal("2")
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    out = decide_step(
        r.id, step.id, StepDecideIn(approve=False, note="No notice"),
        session, hr_user,
    )
    assert out.status == "rejected"
    session.expire_all()
    bal2 = session.get(LeaveBalance, bal.id)
    assert bal2.pending == Decimal("0")


def test_wrong_approver_refused(session):
    emp, hr_user, admin, t = _setup_two_approvers(session)
    outsider = _mk_user_for(session, _mk_emp(session, code="OUT"), "employee")
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
    with pytest.raises(AppError) as e:
        decide_step(r.id, step.id, StepDecideIn(approve=True),
                    session, outsider)
    assert e.value.code in ("wrong_approver", "forbidden")


def test_self_only_chain_refused_at_submit(session):
    _mk_company(session)
    hr_emp = _mk_emp(session, code="HR-SOLO")
    hr_user = _mk_user_for(session, hr_emp, "hr")
    t = _mk_type(session, approval_chain=["hr"])
    _mk_balance(session, hr_emp, t)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=hr_emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, hr_user,
    )
    with pytest.raises(AppError) as e:
        submit_leave_request(r.id, session, hr_user)
    assert e.value.code == "no_eligible_approver"


def test_self_approval_refused(session):
    _mk_company(session)
    emp = _mk_emp(session, code="SUBJ")
    emp_user = _mk_user_for(session, emp, "payroll_admin")
    hr_emp = _mk_emp(session, code="HR-OTHER")
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
    assert step.approver_user_id == hr_user.id
    with pytest.raises(AppError) as e:
        decide_step(r.id, step.id, StepDecideIn(approve=True), session, emp_user)
    assert e.value.code == "self_approval_forbidden"


def test_step_already_decided_refused(session):
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
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    decide_step(r.id, step.id, StepDecideIn(approve=True),
                session, hr_user)
    with pytest.raises(AppError) as e:
        decide_step(r.id, step.id, StepDecideIn(approve=True),
                    session, hr_user)
    assert e.value.code in ("step_already_decided", "wrong_step")


def test_advance_skips_step(session):
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
    out = advance_request(r.id, DecideIn(approve=True, note="Escalate"),
                          session, admin)
    assert out.status == "approved"


def test_decide_shortcut_on_submitted(session):
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
    out = decide_shortcut(r.id, DecideIn(approve=True), session, hr_user)
    assert out.status == "approved"


def test_capture_creates_for_other(session):
    emp = _mk_emp(session)
    t = _mk_type(session)
    _mk_balance(session, emp, t)
    admin = _admin(session)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, admin,
    )
    assert r.captured_by_user_id == admin.id


def test_capture_self_approve_with_note(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    # hr captures for emp, then approves (hr != emp)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, hr_user,
    )
    submit_leave_request(r.id, session, hr_user)
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    # hr_user is the ONLY hr → self-capture-approve path
    # requires a note per _capture_note_if_needed
    out = decide_step(
        r.id, step.id, StepDecideIn(approve=True, note="Verified"),
        session, hr_user,
    )
    assert out.status in ("approved", "submitted")


def test_capture_self_approve_without_note_refused(session):
    emp, hr_user, admin, t = _setup_two_approvers(session)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, hr_user,
    )
    submit_leave_request(r.id, session, hr_user)
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    with pytest.raises(AppError) as e:
        decide_step(r.id, step.id, StepDecideIn(approve=True),
                    session, hr_user)
    assert e.value.code == "capture_requires_note"


def test_attendance_outcome_leave(session):
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
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    decide_step(r.id, step.id, StepDecideIn(approve=True),
                session, hr_user)
    adj = session.scalar(select(Adjustment).where(
        Adjustment.leave_request_id == r.id,
        Adjustment.system_generated.is_(True),
    ))
    assert adj is not None
    assert adj.outcome == "leave"
    assert adj.reason_code == "approved_leave"


def test_attendance_outcome_sick_when_code_configured(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    t.code = "sick_leave"
    s = session.scalar(select(PayrollSettings).limit(1))
    if s is None:
        s = PayrollSettings(
            id=uuid.uuid4(), age_reference_date=None, sdl_applies=None,
            net_pay_floor=Decimal("0"), formula_acks={},
            attendance_earning_map={}, sick_leave_codes=["sick_leave"],
            row_version=1,
        )
        session.add(s)
    else:
        s.sick_leave_codes = ["sick_leave"]
    session.flush()
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
    decide_step(r.id, step.id, StepDecideIn(approve=True),
                session, hr_user)
    adj = session.scalar(select(Adjustment).where(
        Adjustment.leave_request_id == r.id,
        Adjustment.system_generated.is_(True),
    ))
    assert adj is not None
    assert adj.outcome == "sick"


def test_no_absent_expected_after_approval(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    # pre-create an attendance_day marked absent on the leave date
    session.add(AttendanceDay(
        employee_id=emp.id, work_date=date(2026, 6, 1),
        status="absent", first_in=None, last_out=None,
        worked_minutes=0, normal_minutes=0, overtime_minutes=0,
        raw_minutes=0, shift_id=None, flags=[], source_version=0,
        locked=False, row_version=1,
        computed_at=datetime.now(timezone.utc),
    ))
    session.flush()
    session.add(ExceptionItem(
        id=uuid.uuid4(), employee_id=emp.id,
        work_date=date(2026, 6, 1), type="absent_expected",
        source_ref={}, suggested_fix={}, status="open",
    ))
    session.flush()
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
    decide_step(r.id, step.id, StepDecideIn(approve=True),
                session, hr_user)
    # After recompute, the day is leave not absent
    day = session.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp.id,
        AttendanceDay.work_date == date(2026, 6, 1),
    ))
    assert day is not None
    assert day.status == "leave"


def test_revert_on_cancel_approved(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp, hr_user, admin, t = _setup_two_approvers(session)
    # Future date so cancel is allowed
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 12, 1), to_date=date(2026, 12, 1),
        ),
        session, admin,
    )
    submit_leave_request(r.id, session, admin)
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    decide_step(r.id, step.id, StepDecideIn(approve=True),
                session, hr_user)
    from app.api.v1.leave_requests import cancel_leave_request
    out = cancel_leave_request(r.id, session, admin)
    assert out.status == "cancelled"
    reverts = list(session.scalars(select(Adjustment).where(
        Adjustment.leave_request_id == r.id,
        Adjustment.outcome == "revert",
    )).all())
    assert len(reverts) >= 1


def test_requires_approval_false_auto_approves(session):
    _mk_company(session)
    _mk_cal(session, 2026)
    emp = _mk_emp(session)
    t = _mk_type(session, approval_chain=[], requires_approval=False)
    _mk_balance(session, emp, t)
    admin = _admin(session)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, admin,
    )
    out = submit_leave_request(r.id, session, admin)
    assert out.status == "approved"
    steps = list(session.scalars(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
    )).all())
    assert steps == []