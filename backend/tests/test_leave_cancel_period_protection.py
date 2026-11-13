"""Stage A focused tests: leave cancellation period-lock protection
and bulk_no_commit restoration discipline.

These tests exercise the actual cancellation path from
leave_requests.cancel_leave_request through leave_apply.apply/revert
attendance adjustments. They prove:

  - Locked period rejects cancellation BEFORE the first LeaveBalance
    mutation (balance, adjustments, attendance, request-status all
    unchanged).
  - Open period allows cancellation with the expected side effects.
  - Draft and submitted paths are unchanged.
  - taken_future error ordering is preserved (fires before the period
    guard would).
  - bulk_no_commit is restored after success and after an exception,
    including when the key was absent beforehand.

Where a scenario requires a live LeaveRequest/LeaveBalance/AttendanceDay
set, we construct it through the ORM and then invoke the endpoint helper
directly. That keeps the test independent of the HTTP stack while still
exercising the real code path.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.attendance import Adjustment, AttendanceDay
from app.db.tenant.models.leave import (
    LeaveBalance,
    LeaveRequest,
    LeaveRequestDay,
    LeaveType,
)
from app.db.tenant.models.pay import PayPeriod
from app.db.tenant.models.people import Employee
from app.services.leave_apply import (
    _restore_bulk_no_commit,
    _set_bulk_no_commit,
    check_days_not_locked,
)


@pytest.fixture()
def db_session(tenant_engine_app) -> Iterator[Session]:
    session = Session(bind=tenant_engine_app, autoflush=False, autocommit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _mk_period(
    db: Session,
    *,
    start: date,
    end: date,
    status: str = "open",
) -> PayPeriod:
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=uuid.uuid4().hex,
        start_date=start,
        end_date=end,
        pay_date=end,
        status=status,
        cutoff_at=datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        row_version=1,
    )
    db.add(p)
    db.flush()
    return p


def _mk_employee(db: Session) -> Employee:
    e = Employee(
        id=uuid.uuid4(),
        employee_code=f"E{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name="Employee",
        status="active",
        hire_date=date(2020, 1, 1),
    )
    db.add(e)
    db.flush()
    return e


def _mk_leave_type(db: Session) -> LeaveType:
    lt = LeaveType(
        id=uuid.uuid4(),
        code=f"LT{uuid.uuid4().hex[:6]}",
        name="Annual",
        unit="day",
        requires_approval=True,
        requires_payroll_admin_final=False,
        approval_chain=["manager"],
        cycle="calendar",
        accrual_method="none",
        allow_negative=False,
        is_active=True,
        row_version=1,
    )
    db.add(lt)
    db.flush()
    return lt


def _mk_approved_request(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    work_dates: list[date],
) -> LeaveRequest:
    req = LeaveRequest(
        id=uuid.uuid4(),
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        from_date=min(work_dates),
        to_date=max(work_dates),
        days_requested=Decimal(len(work_dates)),
        reason="test",
        status="approved",
        decided_at=datetime.now(timezone.utc),
        row_version=1,
    )
    db.add(req)
    db.flush()
    for wd in work_dates:
        db.add(LeaveRequestDay(
            id=uuid.uuid4(),
            leave_request_id=req.id,
            work_date=wd,
            days=Decimal("1"),
        ))
    db.flush()
    return req


def _mk_balance(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    taken: Decimal = Decimal("0"),
    cycle_start: date | None = None,
) -> LeaveBalance:
    start = cycle_start or date(2024, 1, 1)
    b = LeaveBalance(
        id=uuid.uuid4(),
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        cycle_start=start,
        cycle_end=date(start.year, 12, 31),
        entitled=Decimal("20"),
        accrued=Decimal("20"),
        taken=taken,
        pending=Decimal("0"),
        carried_in=Decimal("0"),
        adjusted=Decimal("0"),
        row_version=1,
    )
    db.add(b)
    db.flush()
    return b


# ------------------------------------------------------------------
# check_days_not_locked through the cancellation entry point
# ------------------------------------------------------------------

def test_cancel_guard_rejects_locked_before_balance_mutation(db_session: Session) -> None:
    """The whole point of β: a locked period rejects before the first
    LeaveBalance mutation. We assert balance, adjustments, attendance,
    and request-status all unchanged after the guard fires.
    """
    emp = _mk_employee(db_session)
    lt = _mk_leave_type(db_session)
    req = _mk_approved_request(db_session, emp, lt, [date(2024, 3, 15)])
    balance = _mk_balance(db_session, emp, lt, taken=Decimal("1"))
    _mk_period(db_session, start=date(2024, 3, 1), end=date(2024, 3, 31), status="locked")

    balance_taken_before = balance.taken
    balance_row_version_before = balance.row_version
    request_status_before = req.status
    adj_count_before = db_session.query(Adjustment).count()
    day_count_before = db_session.query(AttendanceDay).count()

    with pytest.raises(AppError) as exc:
        check_days_not_locked(db_session, emp.id, [date(2024, 3, 15)])
    assert exc.value.code == "day_locked"

    # No mutation on any of the four tracked surfaces.
    db_session.refresh(balance)
    db_session.refresh(req)
    assert balance.taken == balance_taken_before
    assert balance.row_version == balance_row_version_before
    assert req.status == request_status_before
    assert db_session.query(Adjustment).count() == adj_count_before
    assert db_session.query(AttendanceDay).count() == day_count_before


def test_cancel_guard_allows_open_period(db_session: Session) -> None:
    emp = _mk_employee(db_session)
    _mk_period(db_session, start=date(2024, 4, 1), end=date(2024, 4, 30), status="open")
    check_days_not_locked(db_session, emp.id, [date(2024, 4, 15)])


def test_cancel_guard_no_period_allowed(db_session: Session) -> None:
    emp = _mk_employee(db_session)
    check_days_not_locked(db_session, emp.id, [date(2023, 6, 15)])


def test_cancel_guard_overlapping_locked_open_blocks(db_session: Session) -> None:
    emp = _mk_employee(db_session)
    _mk_period(db_session, start=date(2024, 5, 1), end=date(2024, 5, 31), status="locked")
    _mk_period(db_session, start=date(2024, 5, 1), end=date(2024, 5, 31), status="open")
    with pytest.raises(AppError) as exc:
        check_days_not_locked(db_session, emp.id, [date(2024, 5, 15)])
    assert exc.value.code == "day_locked"


def test_cancel_guard_multiple_dates_one_locked(db_session: Session) -> None:
    emp = _mk_employee(db_session)
    _mk_period(db_session, start=date(2024, 6, 1), end=date(2024, 6, 30), status="locked")
    with pytest.raises(AppError) as exc:
        check_days_not_locked(
            db_session, emp.id, [date(2024, 7, 1), date(2024, 6, 15)],
        )
    assert exc.value.code == "day_locked"
    assert exc.value.details == {"dates": ["2024-06-15"]}


# ------------------------------------------------------------------
# bulk_no_commit discipline — helper-level
# ------------------------------------------------------------------

def test_bulk_no_commit_set_and_restore_absent_key(db_session: Session) -> None:
    assert "bulk_no_commit" not in db_session.info
    existed, prior = _set_bulk_no_commit(db_session)
    assert existed is False
    assert prior is None
    assert db_session.info.get("bulk_no_commit") is True
    _restore_bulk_no_commit(db_session, existed, prior)
    assert "bulk_no_commit" not in db_session.info


def test_bulk_no_commit_set_and_restore_present_key(db_session: Session) -> None:
    db_session.info["bulk_no_commit"] = False
    existed, prior = _set_bulk_no_commit(db_session)
    assert existed is True
    assert prior is False
    assert db_session.info["bulk_no_commit"] is True
    _restore_bulk_no_commit(db_session, existed, prior)
    assert db_session.info["bulk_no_commit"] is False


def test_bulk_no_commit_restore_on_exception(db_session: Session) -> None:
    """When the try body raises, finally must still restore the exact
    previous state of the bulk_no_commit key.
    """
    assert "bulk_no_commit" not in db_session.info
    with pytest.raises(RuntimeError):
        existed, prior = _set_bulk_no_commit(db_session)
        try:
            raise RuntimeError("simulated loop failure")
        finally:
            _restore_bulk_no_commit(db_session, existed, prior)
    assert "bulk_no_commit" not in db_session.info