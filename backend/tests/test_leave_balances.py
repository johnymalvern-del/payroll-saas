"""Chapter 3 L1e: leave balance read + adjust (3B.2 + amendment 4).

B-L5a: adds (a) schema tests proving BalanceAdjustIn.reason is required
and non-blank, (b) a FOR UPDATE / advisory-lock SQL capture test, (c) a
real-PostgreSQL concurrent-adjust test proving no duplicate row is created
and no delta is lost on first-time scope adjustment.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.api.v1.leave_balances import (
    adjust_leave_balance,
    get_leave_balance,
    list_leave_balances,
)
from app.api.v1.leave_balances_schemas import BalanceAdjustIn
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.leave import (
    LeaveBalance,
    LeaveBalanceLedger,
    LeaveType,
)
from app.db.tenant.models.people import Employee, User
from app.payroll_engine.leave import available_balance
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
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    slug = f"lb-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="Leave Balance Co",
        admin_username="admin",
        admin_password_hash=hash_password("AdminPassword123!"),
    )
    try:
        yield _DisposableTenant(
            slug=slug,
            tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
    finally:
        _drop_tenant_database(result.tenant_db_name)
        with control_session() as s:
            r = s.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if r is not None:
                s.delete(r)


@pytest.fixture()
def session(disposable_tenant) -> Iterator[Session]:
    url = _TENANT_URL.format(db=disposable_tenant.tenant_db_name)
    engine = create_engine(url, future=True)
    s = Session(bind=engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        engine.dispose()


def _mk_emp(session, code="E1") -> Employee:
    e = Employee(
        employee_code=code, first_name="A", last_name="B",
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly",
        pay_frequency="monthly", row_version=1,
    )
    session.add(e)
    session.flush()
    return e


def _mk_user(session, *, role, employee_id=None) -> User:
    u = User(
        username=f"{role}-{uuid.uuid4().hex[:6]}",
        password_hash="x",
        employee_id=employee_id,
        role=role,
        is_active=True,
        must_change_password=False,
        failed_attempts=0,
        row_version=1,
    )
    session.add(u)
    session.flush()
    return u


def _mk_type(session, *, allow_negative=False, cycle="calendar", code=None) -> LeaveType:
    t = LeaveType(
        name=f"T-{uuid.uuid4().hex[:4]}",
        code=code or f"t{uuid.uuid4().hex[:4]}",
        unit="day",
        paid=True,
        accrual_method="annual",
        accrual_amount=Decimal("20.00"),
        cycle=cycle,
        requires_approval=True,
        allow_negative=allow_negative,
        max_carryover=None,
        approval_chain=["manager", "hr"],
        requires_payroll_admin_final=False,
        is_active=True,
        row_version=1,
    )
    session.add(t)
    session.flush()
    return t


def _mk_balance(
    session, emp, ltype,
    *,
    entitled="0", accrued="0", taken="0", pending="0",
    carried_in="0", adjusted="0",
) -> LeaveBalance:
    b = LeaveBalance(
        employee_id=emp.id,
        leave_type_id=ltype.id,
        cycle_start=date(2026, 1, 1),
        cycle_end=date(2026, 12, 31),
        entitled=Decimal(entitled),
        accrued=Decimal(accrued),
        taken=Decimal(taken),
        pending=Decimal(pending),
        carried_in=Decimal(carried_in),
        adjusted=Decimal(adjusted),
        row_version=1,
    )
    session.add(b)
    session.flush()
    return b


# ---------------------------------------------------------------------------
# available_balance formula (amendment 4)
# ---------------------------------------------------------------------------

def test_available_balance_uses_accrued_not_entitled():
    """entitled is informational; only accrued drives availability.

    10 accrued + 5 carried_in + (-1) adjusted - 3 taken - 2 pending = 9.
    If `entitled` (20) were added, the result would be 29.
    """
    emp = type("E", (), {"id": uuid.uuid4()})()
    ltype = type("T", (), {"id": uuid.uuid4()})()
    b = LeaveBalance(
        employee_id=emp.id, leave_type_id=ltype.id,
        cycle_start=date(2026, 1, 1), cycle_end=date(2026, 12, 31),
        entitled=Decimal("20"),
        accrued=Decimal("10"),
        taken=Decimal("3"),
        pending=Decimal("2"),
        carried_in=Decimal("5"),
        adjusted=Decimal("-1"),
        row_version=1,
    )
    assert available_balance(b) == Decimal("9")


# ---------------------------------------------------------------------------
# List / get scoping
# ---------------------------------------------------------------------------

def test_list_self_only_returns_own(session):
    emp1 = _mk_emp(session, "E1")
    emp2 = _mk_emp(session, "E2")
    t = _mk_type(session)
    _mk_balance(session, emp1, t, accrued="10")
    _mk_balance(session, emp2, t, accrued="10")
    u = _mk_user(session, role="employee", employee_id=emp1.id)

    out = list_leave_balances(
        session, u,
        employee_id=None, leave_type_id=None,
        cycle_start_gte=None, cycle_start_lte=None,
        limit=100, cursor=None,
    )
    assert all(r.employee_id == emp1.id for r in out.items)
    assert len(out.items) == 1


def test_list_leave_approve_sees_in_scope(session):
    emp = _mk_emp(session)
    t = _mk_type(session)
    _mk_balance(session, emp, t, accrued="10")
    u = _mk_user(session, role="hr")

    out = list_leave_balances(
        session, u,
        employee_id=emp.id, leave_type_id=None,
        cycle_start_gte=None, cycle_start_lte=None,
        limit=100, cursor=None,
    )
    assert len(out.items) == 1


def test_get_out_of_scope_404(session):
    emp = _mk_emp(session)
    t = _mk_type(session)
    b = _mk_balance(session, emp, t)
    other = _mk_user(session, role="employee", employee_id=None)
    with pytest.raises(AppError) as exc:
        get_leave_balance(b.id, session, other)
    assert exc.value.code in ("not_found", "no_employee_record")


# ---------------------------------------------------------------------------
# Adjust
# ---------------------------------------------------------------------------

def test_adjust_positive_ok(session):
    emp = _mk_emp(session)
    t = _mk_type(session)
    _mk_balance(session, emp, t, accrued="10")
    u = _mk_user(session, role="hr")

    out = adjust_leave_balance(
        BalanceAdjustIn(
            employee_id=emp.id,
            leave_type_id=t.id,
            delta=Decimal("5"),
            reason="Holiday bonus",
        ),
        session, u,
    )
    assert out.balance.adjusted == Decimal("5")
    assert out.balance.available == Decimal("15")


def test_adjust_negative_refused_without_allow_negative(session):
    emp = _mk_emp(session)
    t = _mk_type(session, allow_negative=False)
    _mk_balance(session, emp, t, accrued="3")
    u = _mk_user(session, role="hr")

    with pytest.raises(AppError) as exc:
        adjust_leave_balance(
            BalanceAdjustIn(
                employee_id=emp.id,
                leave_type_id=t.id,
                delta=Decimal("-5"),
                reason="Correction",
            ),
            session, u,
        )
    assert exc.value.code == "insufficient_balance"


def test_adjust_negative_allowed_with_allow_negative(session):
    emp = _mk_emp(session)
    t = _mk_type(session, allow_negative=True)
    _mk_balance(session, emp, t, accrued="3")
    u = _mk_user(session, role="hr")

    out = adjust_leave_balance(
        BalanceAdjustIn(
            employee_id=emp.id,
            leave_type_id=t.id,
            delta=Decimal("-5"),
            reason="Correction",
        ),
        session, u,
    )
    assert out.balance.available == Decimal("-2")


def test_adjust_writes_ledger_row(session):
    emp = _mk_emp(session)
    t = _mk_type(session)
    _mk_balance(session, emp, t, accrued="10")
    u = _mk_user(session, role="hr")

    out = adjust_leave_balance(
        BalanceAdjustIn(
            employee_id=emp.id,
            leave_type_id=t.id,
            delta=Decimal("4"),
            reason="Adjust",
        ),
        session, u,
    )
    ledger = session.get(LeaveBalanceLedger, out.ledger_entry_id)
    assert ledger is not None
    assert ledger.delta == Decimal("4")
    assert ledger.reason == "adjustment"


def test_adjust_creates_missing_live_cycle(session):
    emp = _mk_emp(session)
    t = _mk_type(session, cycle="calendar")
    u = _mk_user(session, role="hr")
    out = adjust_leave_balance(
        BalanceAdjustIn(
            employee_id=emp.id,
            leave_type_id=t.id,
            delta=Decimal("7"),
            reason="Initial",
        ),
        session, u,
    )
    assert out.balance.adjusted == Decimal("7")
    assert out.balance.cycle_start.year == date.today().year


def test_adjust_closed_cycle_requires_finalise(session):
    emp = _mk_emp(session)
    t = _mk_type(session)
    b = LeaveBalance(
        employee_id=emp.id, leave_type_id=t.id,
        cycle_start=date(2024, 1, 1), cycle_end=date(2024, 12, 31),
        entitled=Decimal("0"), accrued=Decimal("5"),
        taken=Decimal("0"), pending=Decimal("0"),
        carried_in=Decimal("0"), adjusted=Decimal("0"),
        row_version=1,
    )
    session.add(b)
    session.flush()
    u = _mk_user(session, role="hr")
    with pytest.raises(AppError) as exc:
        adjust_leave_balance(
            BalanceAdjustIn(
                employee_id=emp.id,
                leave_type_id=t.id,
                cycle_start=date(2024, 1, 1),
                delta=Decimal("1"),
                reason="Late",
            ),
            session, u,
        )
    assert exc.value.code == "forbidden"


# ---------------------------------------------------------------------------
# GET never writes (amendment 3)
# ---------------------------------------------------------------------------

def test_get_never_writes_ledger(session):
    from sqlalchemy import func as _f

    emp = _mk_emp(session)
    t = _mk_type(session)
    _mk_balance(session, emp, t, accrued="10")
    u = _mk_user(session, role="hr")

    before = session.scalar(select(_f.count()).select_from(LeaveBalanceLedger))
    list_leave_balances(
        session, u,
        employee_id=None, leave_type_id=None,
        cycle_start_gte=None, cycle_start_lte=None,
        limit=100, cursor=None,
    )
    after = session.scalar(select(_f.count()).select_from(LeaveBalanceLedger))
    assert after == before


# ---------------------------------------------------------------------------
# B-L5a Task A: BalanceAdjustIn.reason is required and non-blank
# ---------------------------------------------------------------------------

def test_schema_missing_reason_rejected():
    with pytest.raises(ValidationError):
        BalanceAdjustIn(
            employee_id=uuid.uuid4(),
            leave_type_id=uuid.uuid4(),
            delta=Decimal("1"),
        )


def test_schema_empty_reason_rejected():
    with pytest.raises(ValidationError):
        BalanceAdjustIn(
            employee_id=uuid.uuid4(),
            leave_type_id=uuid.uuid4(),
            delta=Decimal("1"),
            reason="",
        )


def test_schema_whitespace_reason_rejected():
    with pytest.raises(ValidationError):
        BalanceAdjustIn(
            employee_id=uuid.uuid4(),
            leave_type_id=uuid.uuid4(),
            delta=Decimal("1"),
            reason="   ",
        )


def test_schema_valid_reason_accepted():
    p = BalanceAdjustIn(
        employee_id=uuid.uuid4(),
        leave_type_id=uuid.uuid4(),
        delta=Decimal("1"),
        reason="Holiday bonus",
    )
    assert p.reason == "Holiday bonus"


# ---------------------------------------------------------------------------
# B-L5a Task B: closed-cycle success, advisory lock, concurrency
# ---------------------------------------------------------------------------

def test_adjust_closed_cycle_succeeds_with_payroll_finalise(session):
    """A payroll_admin (PAYROLL_FINALISE) can adjust a closed cycle."""
    emp = _mk_emp(session)
    t = _mk_type(session)
    b = LeaveBalance(
        employee_id=emp.id, leave_type_id=t.id,
        cycle_start=date(2024, 1, 1), cycle_end=date(2024, 12, 31),
        entitled=Decimal("0"), accrued=Decimal("5"),
        taken=Decimal("0"), pending=Decimal("0"),
        carried_in=Decimal("0"), adjusted=Decimal("0"),
        row_version=1,
    )
    session.add(b)
    session.flush()
    admin = _mk_user(session, role="payroll_admin")

    out = adjust_leave_balance(
        BalanceAdjustIn(
            employee_id=emp.id,
            leave_type_id=t.id,
            cycle_start=date(2024, 1, 1),
            delta=Decimal("2"),
            reason="Late correction",
        ),
        session, admin,
    )
    assert out.balance.adjusted == Decimal("2")
    assert out.balance.cycle_end == date(2024, 12, 31)


def test_adjust_emits_advisory_lock_and_for_update_sql(session):
    """The adjust path emits pg_advisory_xact_lock and FOR UPDATE."""
    emp = _mk_emp(session)
    t = _mk_type(session)
    _mk_balance(session, emp, t, accrued="10")
    u = _mk_user(session, role="hr")

    captured: list[str] = []
    bind = session.get_bind()
    target = getattr(bind, "engine", bind)

    def _capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    event.listen(target, "before_cursor_execute", _capture)
    try:
        adjust_leave_balance(
            BalanceAdjustIn(
                employee_id=emp.id, leave_type_id=t.id,
                delta=Decimal("1"), reason="Test",
            ),
            session, u,
        )
    finally:
        event.remove(target, "before_cursor_execute", _capture)

    joined = "\n".join(captured).lower()
    assert "pg_advisory_xact_lock" in joined, (
        f"advisory lock missing; captured={captured}"
    )
    assert "for update" in joined, (
        f"FOR UPDATE missing; captured={captured}"
    )


def test_adjust_concurrent_first_time_single_row(disposable_tenant):
    """Two concurrent adjusts on a previously-empty scope produce one row
    with adjusted == sum of both deltas; ledger has exactly two rows.

    Real PostgreSQL — each worker uses its own engine and session.
    """
    url = _TENANT_URL.format(db=disposable_tenant.tenant_db_name)

    # Setup in one session
    eng = create_engine(url, future=True)
    setup = Session(bind=eng)
    emp = _mk_emp(setup)
    t = _mk_type(setup)
    hr_user = _mk_user(setup, role="hr")
    emp_id, t_id, user_id = emp.id, t.id, hr_user.id
    setup.commit()
    setup.close()
    eng.dispose()

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def worker(delta: str) -> None:
        w_eng = create_engine(url, future=True)
        s = Session(bind=w_eng)
        try:
            user = s.scalar(select(User).where(User.id == user_id))
            payload = BalanceAdjustIn(
                employee_id=emp_id, leave_type_id=t_id,
                delta=Decimal(delta), reason=f"concurrent {delta}",
            )
            barrier.wait(timeout=10)
            adjust_leave_balance(payload, s, user)
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))
        finally:
            s.close()
            w_eng.dispose()

    threads = [
        threading.Thread(target=worker, args=("3",)),
        threading.Thread(target=worker, args=("5",)),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)

    assert errors == [], errors

    # Verify
    v_eng = create_engine(url, future=True)
    verify = Session(bind=v_eng)
    try:
        rows = list(verify.scalars(select(LeaveBalance).where(
            LeaveBalance.employee_id == emp_id,
            LeaveBalance.leave_type_id == t_id,
        )).all())
        assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
        assert rows[0].adjusted == Decimal("8"), (
            f"lost update: adjusted={rows[0].adjusted}, expected 8"
        )

        ledger = list(verify.scalars(select(LeaveBalanceLedger).where(
            LeaveBalanceLedger.employee_id == emp_id,
            LeaveBalanceLedger.leave_type_id == t_id,
            LeaveBalanceLedger.reason == "adjustment",
        )).all())
        assert len(ledger) == 2, f"expected 2 ledger rows, got {len(ledger)}"
    finally:
        verify.close()
        v_eng.dispose()