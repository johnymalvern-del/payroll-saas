"""Chapter 3 L1e: accrual service + run endpoint (3B.3 + amendment 3).

B-L5a: adds (a) an advisory-lock SQL capture test, (b) a real-PostgreSQL
concurrent-accrual test proving no duplicate period keys, (c) a rollback
test proving a mid-run failure leaves no partial state.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.api.v1.leave_accruals import run_accruals
from app.api.v1.leave_accruals_schemas import AccrualRunIn
from app.api.v1.leave_balances import list_leave_balances
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.leave import (
    LeaveBalance,
    LeaveBalanceLedger,
    LeaveType,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, User
from app.payroll_engine.leave import accrue_all_employees
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
    slug = f"la-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="Leave Accrual Co",
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


def _admin(session) -> User:
    u = session.scalar(select(User).where(User.username == "admin"))
    assert u is not None
    return u


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


def _mk_type(session, *, method="annual", amount="12.00",
             cycle="calendar", max_carryover=None) -> LeaveType:
    t = LeaveType(
        name=f"T-{uuid.uuid4().hex[:4]}",
        code=f"t{uuid.uuid4().hex[:4]}",
        unit="day",
        paid=True,
        accrual_method=method,
        accrual_amount=Decimal(amount) if amount is not None else None,
        cycle=cycle,
        requires_approval=True,
        allow_negative=False,
        max_carryover=(
            Decimal(max_carryover) if max_carryover is not None else None
        ),
        approval_chain=["manager", "hr"],
        requires_payroll_admin_final=False,
        is_active=True,
        row_version=1,
    )
    session.add(t)
    session.flush()
    return t


def _settings(session) -> PayrollSettings:
    s = session.scalar(select(PayrollSettings).limit(1))
    if s is None:
        s = PayrollSettings(
            id=uuid.uuid4(),
            age_reference_date=None,
            sdl_applies=None,
            net_pay_floor=Decimal("0"),
            formula_acks={},
            attendance_earning_map={},
            sick_leave_codes=[],
            row_version=1,
        )
        session.add(s)
        session.flush()
    return s


def test_accrual_monthly_creates_rows(session):
    _settings(session)
    emp = _mk_emp(session)
    _mk_type(session, method="monthly", amount="1.00")
    as_of = date(2026, 3, 15)
    result = accrue_all_employees(session, as_of)
    # Jan, Feb, Mar = 3 monthly rows
    assert result["rows_written"] == 3
    ledger = list(session.scalars(select(LeaveBalanceLedger)).all())
    assert len(ledger) == 3


def test_accrual_is_idempotent_same_month(session):
    _settings(session)
    _mk_emp(session)
    _mk_type(session, method="monthly", amount="1.00")
    as_of = date(2026, 3, 15)
    accrue_all_employees(session, as_of)
    second = accrue_all_employees(session, as_of)
    assert second["rows_written"] == 0
    count = session.scalar(select(func.count()).select_from(LeaveBalanceLedger))
    assert count == 3


def test_accrual_annual_drips_one_twelfth(session):
    _settings(session)
    emp = _mk_emp(session)
    _mk_type(session, method="annual", amount="120.00")
    as_of = date(2026, 2, 15)
    accrue_all_employees(session, as_of)
    bal = session.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == emp.id
    ))
    # Jan + Feb = 2/12 of 120 = 20.00
    assert bal.accrued == Decimal("20.0000")


def test_accrual_fixed_grants_once(session):
    _settings(session)
    emp = _mk_emp(session)
    _mk_type(session, method="fixed", amount="15.00")
    as_of = date(2026, 6, 15)
    accrue_all_employees(session, as_of)
    accrue_all_employees(session, as_of)
    count = session.scalar(select(func.count()).select_from(LeaveBalanceLedger))
    assert count == 1
    bal = session.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == emp.id
    ))
    assert bal.accrued == Decimal("15.0000")


def test_accrual_none_creates_nothing(session):
    _settings(session)
    _mk_emp(session)
    _mk_type(session, method="none", amount=None)
    result = accrue_all_employees(session, date(2026, 3, 15))
    assert result["rows_written"] == 0


def test_accrual_carry_over_respects_max(session):
    _settings(session)
    emp = _mk_emp(session)
    t = _mk_type(session, method="monthly", amount="0", max_carryover="3.00")
    # Prior 2025 balance with 10 available
    session.add(LeaveBalance(
        employee_id=emp.id, leave_type_id=t.id,
        cycle_start=date(2025, 1, 1), cycle_end=date(2025, 12, 31),
        entitled=Decimal("10"), accrued=Decimal("10"),
        taken=Decimal("0"), pending=Decimal("0"),
        carried_in=Decimal("0"), adjusted=Decimal("0"),
        row_version=1,
    ))
    session.flush()
    accrue_all_employees(session, date(2026, 1, 15))
    new_bal = session.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == emp.id,
        LeaveBalance.cycle_start == date(2026, 1, 1),
    ))
    assert new_bal is not None
    assert new_bal.carried_in == Decimal("3.00")


def test_accrual_carry_over_all_remaining_when_no_max(session):
    _settings(session)
    emp = _mk_emp(session)
    t = _mk_type(session, method="monthly", amount="0", max_carryover=None)
    session.add(LeaveBalance(
        employee_id=emp.id, leave_type_id=t.id,
        cycle_start=date(2025, 1, 1), cycle_end=date(2025, 12, 31),
        entitled=Decimal("10"), accrued=Decimal("10"),
        taken=Decimal("3"), pending=Decimal("0"),
        carried_in=Decimal("0"), adjusted=Decimal("0"),
        row_version=1,
    ))
    session.flush()
    accrue_all_employees(session, date(2026, 1, 15))
    new_bal = session.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == emp.id,
        LeaveBalance.cycle_start == date(2026, 1, 1),
    ))
    assert new_bal.carried_in == Decimal("7")


def test_run_endpoint_returns_counts(session):
    _settings(session)
    _mk_emp(session)
    _mk_type(session, method="monthly", amount="1.00")
    admin = _admin(session)
    out = run_accruals(session, admin, AccrualRunIn(as_of_date=date(2026, 2, 15)))
    assert out.rows_written == 2
    assert out.employees_touched == 1
    assert out.as_of == date(2026, 2, 15)


def test_balances_list_reports_stale_when_never_run(session):
    _settings(session)
    emp = _mk_emp(session)
    t = _mk_type(session)
    session.add(LeaveBalance(
        employee_id=emp.id, leave_type_id=t.id,
        cycle_start=date(2026, 1, 1), cycle_end=date(2026, 12, 31),
        entitled=Decimal("0"), accrued=Decimal("0"),
        taken=Decimal("0"), pending=Decimal("0"),
        carried_in=Decimal("0"), adjusted=Decimal("0"),
        row_version=1,
    ))
    session.flush()
    admin = _admin(session)
    out = list_leave_balances(
        session, admin,
        employee_id=None, leave_type_id=None,
        cycle_start_gte=None, cycle_start_lte=None,
        limit=100, cursor=None,
    )
    assert out.accrued_as_of is None
    assert out.accrual_stale is True


def test_balances_list_fresh_after_run(session):
    _settings(session)
    emp = _mk_emp(session)
    t = _mk_type(session)
    session.add(LeaveBalance(
        employee_id=emp.id, leave_type_id=t.id,
        cycle_start=date(2026, 1, 1), cycle_end=date(2026, 12, 31),
        entitled=Decimal("0"), accrued=Decimal("0"),
        taken=Decimal("0"), pending=Decimal("0"),
        carried_in=Decimal("0"), adjusted=Decimal("0"),
        row_version=1,
    ))
    session.flush()
    admin = _admin(session)
    run_accruals(session, admin, AccrualRunIn(as_of_date=date(2026, 1, 15)))
    out = list_leave_balances(
        session, admin,
        employee_id=None, leave_type_id=None,
        cycle_start_gte=None, cycle_start_lte=None,
        limit=100, cursor=None,
    )
    assert out.accrued_as_of is not None
    assert out.accrual_stale is False


# ---------------------------------------------------------------------------
# B-L5a Task C: advisory lock SQL + concurrency + rollback
# ---------------------------------------------------------------------------

def test_accrual_emits_advisory_lock_sql(session):
    """accrue_all_employees must acquire pg_advisory_xact_lock first."""
    _settings(session)
    _mk_emp(session)
    _mk_type(session, method="monthly", amount="1.00")

    captured: list[str] = []
    bind = session.get_bind()
    target = getattr(bind, "engine", bind)

    def _capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    event.listen(target, "before_cursor_execute", _capture)
    try:
        accrue_all_employees(session, date(2026, 3, 15))
    finally:
        event.remove(target, "before_cursor_execute", _capture)

    joined = "\n".join(captured).lower()
    assert "pg_advisory_xact_lock" in joined, (
        f"advisory lock missing; captured={captured}"
    )


def test_accrual_concurrent_no_duplicate_ledger(disposable_tenant):
    """Two concurrent accrual runs produce the same ledger as one run."""
    url = _TENANT_URL.format(db=disposable_tenant.tenant_db_name)

    # Setup
    eng = create_engine(url, future=True)
    setup = Session(bind=eng)
    _settings(setup)
    _mk_emp(setup)
    _mk_type(setup, method="monthly", amount="1.00")
    setup.commit()
    setup.close()
    eng.dispose()

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def worker() -> None:
        w_eng = create_engine(url, future=True)
        s = Session(bind=w_eng)
        try:
            barrier.wait(timeout=10)
            accrue_all_employees(s, date(2026, 3, 15))
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))
        finally:
            s.close()
            w_eng.dispose()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)

    assert errors == [], errors

    # Verify
    v_eng = create_engine(url, future=True)
    verify = Session(bind=v_eng)
    try:
        count = verify.scalar(
            select(func.count()).select_from(LeaveBalanceLedger)
        )
        # Jan + Feb + Mar = 3 rows, not 6
        assert count == 3, f"duplicate accrual: got {count} ledger rows"
    finally:
        verify.close()
        v_eng.dispose()


def test_accrual_rollback_on_mid_run_failure(session, monkeypatch):
    """A mid-run exception leaves no partial state (rollback proven)."""
    _settings(session)
    _mk_emp(session)
    _mk_type(session, method="monthly", amount="1.00")

    from app.payroll_engine import leave as leave_engine

    def _boom(lt):
        raise RuntimeError("simulated failure mid-accrual")

    monkeypatch.setattr(leave_engine, "_accrual_amount_for", _boom)

    with pytest.raises(RuntimeError):
        accrue_all_employees(session, date(2026, 3, 15))

    session.rollback()
    after = session.scalar(
        select(func.count()).select_from(LeaveBalanceLedger)
    )
    assert after == 0, f"partial accrual committed: {after} ledger rows"