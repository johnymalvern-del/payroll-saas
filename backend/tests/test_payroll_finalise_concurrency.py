"""M6 Part 2 Stage 1 — concurrency safety on finalise/reopen/preview.

Verifies:
1. Sequential double-finalise returns a clean 409 period_locked (the
   existing status-guard regression baseline).
2. Each mutator (`run_preview`, `finalise`, `reopen`) issues
   `SELECT ... FOR UPDATE` on `pay_period` at the top of the function.

The lock mechanism is what makes the race safe: two concurrent callers both
issue `with_for_update`, one blocks on the row lock, and once the winner
commits, the loser observes the updated status via `populate_existing` and
returns a clean 409 instead of a raw `IntegrityError` 500
(uq_payslip_period_employee_rev).

True concurrency simulation (two independent sessions racing a real lock)
requires multi-session test infrastructure that the current suite does not
provide. That gap is documented here; the mechanism test is the reliable
proxy.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.core.errors import AppError
from app.db.tenant.models.pay import PayPeriod
from app.db.tenant.models.people import Employee
from app.services.payroll_runner import finalise, reopen, run_preview


@pytest.fixture()
def db(_leave_session_shared):
    return _leave_session_shared


def _mk_employee(session, code="E1"):
    emp = Employee(
        employee_code=code,
        first_name="A",
        last_name="B",
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


def _mk_period(session, status="open"):
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"2026-{uuid.uuid4().hex[:8]}",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        pay_date=date(2026, 12, 5),
        status=status,
        cutoff_at=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
        row_version=1,
    )
    session.add(p)
    session.flush()
    return p


def _user():
    return SimpleNamespace(id=uuid.uuid4(), role="payroll_admin")


def _capture_sql(session):
    """Attach a listener that records every SQL statement on the session's bind."""
    captured: list[str] = []

    def _listener(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", _listener)
    return captured, bind, _listener


def _release_sql(bind, listener):
    event.remove(bind, "before_cursor_execute", listener)


def test_second_finalise_sequential_returns_409(db):
    """After a finalise that reaches the lock-and-status-guard path, a repeat
    call returns 409 period_locked. Uses the exact guard that Stage 1
    preserves; the test fails if the guard is ever removed."""
    emp = _mk_employee(db)
    period = _mk_period(db)

    # First attempt: may refuse downstream (no settings, no statutory
    # tables). Not relevant — we only care about the guard.
    try:
        finalise(db, _user(), period)
    except AppError:
        pass
    except Exception:
        pass

    # Force locked state if pipeline refused early; if pipeline succeeded,
    # status is already "locked".
    if period.status != "locked":
        period.status = "locked"
        db.flush()

    # Second call must observe locked status via the lock refresh and 409.
    with pytest.raises(AppError) as e:
        finalise(db, _user(), period)
    assert e.value.code == "period_locked"


@pytest.mark.parametrize("mutator_name", ["finalise", "reopen", "run_preview"])
def test_row_lock_issued_for_all_mutators(db, mutator_name):
    """Stage 1: each mutator must issue SELECT ... FOR UPDATE on pay_period.

    This is a MECHANISM test. It proves the lock is requested. The actual
    concurrency safety (two callers racing a real lock) requires
    multi-session integration infrastructure not available in this unit
    suite — but the mechanism is what eliminates the race, so its presence
    is a strong precondition.

    If this test fails, it means the with_for_update call was removed or
    the SELECT was rewritten in a way that dropped the row lock.
    """
    period = _mk_period(db)
    if mutator_name == "reopen":
        period.status = "locked"
        db.flush()

    captured, bind, listener = _capture_sql(db)
    try:
        try:
            if mutator_name == "finalise":
                finalise(db, _user(), period)
            elif mutator_name == "run_preview":
                run_preview(db, _user(), period)
            elif mutator_name == "reopen":
                reopen(db, _user(), period, reason="test")
        except AppError:
            pass  # downstream guards (formulas, open exceptions) may refuse
        except Exception:
            pass
    finally:
        _release_sql(bind, listener)

    lock_sqls = [
        s for s in captured
        if "for update" in s.lower() and "pay_period" in s
    ]
    assert lock_sqls, (
        f"Stage 1: expected SELECT ... FOR UPDATE on pay_period in "
        f"{mutator_name}; captured {len(captured)} statement(s): "
        f"{captured[:5]}"
    )