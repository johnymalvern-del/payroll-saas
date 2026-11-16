"""Stage B Batch 1 — adjustment + audit atomicity tests.

Verify that _apply_adjustment commits the adjustment row, the recomputed
AttendanceDay/AttendanceSegment state, the adjustment's new_value snapshot,
and the AuditLog row as one transaction when the caller is NOT in bulk
mode. And verify that bulk_adjust (which sets bulk_no_commit=True) still
commits the whole batch as one transaction.

What the fix changes:
  BEFORE: _persist_day (inside recompute_day) called db.commit() mid-flow
          when bulk_no_commit was not set. That committed the adjustment
          insert and the attendance recompute, but NOT adj.new_value and
          NOT the AuditLog row. A crash between those two commits left the
          adjustment applied without an audit trail.
  AFTER:  _apply_adjustment sets bulk_no_commit=True for its own scope
          when the caller has not set it. _persist_day then flushes instead
          of committing. All writes commit together at the end of
          _apply_adjustment.

These tests exercise the contract at the service boundary, using the real
recompute_day. Where a test needs recompute_day to fail, it patches it.
The country_calendar row required by _load_holiday_set is seeded via
_mk_cal, mirroring test_attendance.py. The shift and rate rule required
for recompute_day to produce "worked" are seeded via _mk_shift / _mk_rule,
also mirroring test_attendance.py.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.exceptions import _apply_adjustment
from app.api.v1.exceptions_schemas import CustomAdjustmentIn
from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import (
    AttendanceDay,
    Adjustment,
    CountryCalendar,
    Shift,
    ShiftRateRule,
)
from app.db.tenant.models.people import Employee, User
from app.db.tenant.models.platform import AuditLog
from app.db.tenant.session import get_tenant_engine
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)

from dataclasses import dataclass


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    slug = f"adjtx-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="AdjTx Test",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(
            slug=result.slug,
            tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
    finally:
        try:
            _drop_tenant_database(db_name)
        except Exception:
            pass
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


@pytest.fixture()
def db(disposable_tenant: _DisposableTenant) -> Iterator[Session]:
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


def _mk_cal(db: Session, year: int) -> None:
    """Seed a country_calendar row so _load_holiday_set finds at least one
    row for the year. Mirrors test_attendance.py::_mk_cal.
    """
    db.add(CountryCalendar(
        country_code="ZA",
        holiday_date=date(year, 12, 25),
        name="Xmas",
        source_ref="test",
    ))
    db.commit()


def _mk_shift(db: Session) -> Shift:
    """Seed a weekday day shift with a rate rule. Mirrors
    test_attendance.py::_mk_shift + _mk_rule. Returns the shift.
    """
    s = Shift(
        name=f"S-{uuid.uuid4().hex[:6]}",
        start_time=time(8, 0),
        length_minutes=480,
        unpaid_break_minutes=60,
        paid_break_minutes=0,
        grace_late_minutes=0,
        grace_early_minutes=0,
        grace_mode="threshold",
        rounding_minutes=0,
        rounding_mode="nearest",
        min_overtime_minutes=0,
        overtime_requires_approval=False,
        max_shift_minutes=720,
        match_tolerance_minutes=60,
        salaried_premium_mode="full",
        pay_early_arrival=False,
        is_active=True,
        row_version=1,
    )
    db.add(s)
    db.commit()
    db.add(ShiftRateRule(
        shift_id=s.id,
        day_type="weekday",
        kind="normal",
        tier=1,
        tier_up_to_minutes=None,
        method="multiplier",
        value=Decimal("1.0"),
        flat_unit=None,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    ))
    db.commit()
    return s


def _mk_user(db: Session, *, role: str = "hr") -> User:
    u = User(
        username=normalise_username(f"u-{uuid.uuid4().hex[:8]}"),
        password_hash=hash_password("TestPassword123!"),
        role=role,
        is_active=True,
        must_change_password=False,
        employee_id=None,
        row_version=1,
    )
    db.add(u)
    db.commit()
    return u


def _mk_employee(db: Session, *, default_shift_id: uuid.UUID | None = None) -> Employee:
    code = f"TX{uuid.uuid4().hex[:8]}"
    e = Employee(
        employee_code=code,
        first_name="Tx",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        default_shift_id=default_shift_id,
        row_version=1,
    )
    db.add(e)
    db.commit()
    return e


def _mk_day(db: Session, employee_id: uuid.UUID, work_date: date) -> AttendanceDay:
    d = AttendanceDay(
        employee_id=employee_id,
        work_date=work_date,
        status="absent",
        normal_minutes=0,
        worked_minutes=0,
        overtime_minutes=0,
        raw_minutes=0,
        shift_id=None,
        flags=[],
        source_version=0,
        locked=False,
        row_version=1,
    )
    db.add(d)
    db.commit()
    return d


def _custom_for_worked() -> CustomAdjustmentIn:
    return CustomAdjustmentIn(
        outcome="worked",
        time_in=datetime(2024, 5, 15, 8, 0, tzinfo=timezone.utc),
        time_out=datetime(2024, 5, 15, 16, 0, tzinfo=timezone.utc),
        reason_code="system_correction",
        note="atomicity test",
    )


# ----------------------------------------------------------------------
# 1. Successful atomic completion (single non-bulk call)
# ----------------------------------------------------------------------

def test_single_apply_adjustment_writes_are_atomic(db: Session) -> None:
    """One call to _apply_adjustment (non-bulk mode) produces:
      - an Adjustment row
      - an updated AttendanceDay (with recomputed minutes)
      - an AuditLog row with entity_type='adjustment'
    All three are visible after the call, none of them is partially
    written. The Adjustment row has BOTH old_value and new_value set.
    A shift is seeded so recompute_day can produce "worked".
    """
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    user = _mk_user(db)
    emp = _mk_employee(db, default_shift_id=shift.id)
    work_date = date(2024, 5, 15)
    _mk_day(db, emp.id, work_date)
    db.rollback()

    adj_id, day_status = _apply_adjustment(
        db, user, emp.id, work_date, _custom_for_worked(),
    )
    assert day_status == "worked"

    adj = db.get(Adjustment, adj_id)
    assert adj is not None
    assert adj.outcome == "worked"
    assert adj.old_value is not None, "old_value must be captured before recompute"
    assert adj.new_value is not None, "new_value must be captured after recompute"

    day = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp.id,
        AttendanceDay.work_date == work_date,
    ))
    assert day is not None
    assert day.status == "worked"
    assert day.worked_minutes > 0

    audit = db.scalar(select(AuditLog).where(
        AuditLog.entity_type == "adjustment",
        AuditLog.entity_id == str(adj.id),
    ))
    assert audit is not None, "AuditLog row must exist for this adjustment"
    assert audit.action == "attendance.adjustment.create"


# ----------------------------------------------------------------------
# 2. Rollback on failure
# ----------------------------------------------------------------------

def test_single_apply_adjustment_rolls_back_on_recompute_failure(
    db: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If recompute_day raises after _persist_adjustment, everything rolls
    back: no Adjustment, no AttendanceDay change, no AuditLog.

    recompute_day is patched to raise before it does any work, so the
    shift seeding is not strictly required for this test — but it is
    included for fixture parity with the other tests.
    """
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    user = _mk_user(db)
    emp = _mk_employee(db, default_shift_id=shift.id)
    work_date = date(2024, 5, 15)
    _mk_day(db, emp.id, work_date)
    db.rollback()

    adj_before = db.scalar(select(Adjustment.id).where(
        Adjustment.employee_id == emp.id,
        Adjustment.work_date == work_date,
    ))
    assert adj_before is None
    audit_before = db.scalar(select(AuditLog.id).where(
        AuditLog.entity_type == "adjustment",
    ))
    assert audit_before is None

    import app.api.v1.exceptions as exc_mod
    def _boom(db_, employee_id, work_date):
        raise RuntimeError("simulated recompute failure")
    monkeypatch.setattr(exc_mod, "recompute_day", _boom)

    with pytest.raises(RuntimeError, match="simulated recompute failure"):
        _apply_adjustment(db, user, emp.id, work_date, _custom_for_worked())

    db.rollback()
    adj_after = db.scalar(select(Adjustment.id).where(
        Adjustment.employee_id == emp.id,
        Adjustment.work_date == work_date,
    ))
    assert adj_after is None, "no Adjustment row must persist after rollback"
    audit_after = db.scalar(select(AuditLog.id).where(
        AuditLog.entity_type == "adjustment",
    ))
    assert audit_after is None, "no AuditLog must persist after rollback"
    day = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == emp.id,
        AttendanceDay.work_date == work_date,
    ))
    assert day is not None
    assert day.status == "absent", "AttendanceDay must be unchanged after rollback"


# ----------------------------------------------------------------------
# 3. bulk_adjust success (bulk_no_commit preserved)
# ----------------------------------------------------------------------

def test_bulk_adjust_two_items_commit_together(db: Session) -> None:
    """Call _apply_adjustment twice inside a simulated bulk loop with
    bulk_no_commit=True set before the loop; the final commit covers both
    adjustments + both AuditLogs atomically.
    """
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    user = _mk_user(db)
    emp1 = _mk_employee(db, default_shift_id=shift.id)
    emp2 = _mk_employee(db, default_shift_id=shift.id)
    d1 = date(2024, 5, 15)
    d2 = date(2024, 5, 16)
    _mk_day(db, emp1.id, d1)
    _mk_day(db, emp2.id, d2)
    db.rollback()

    db.info["bulk_no_commit"] = True
    try:
        adj_id_1, _ = _apply_adjustment(db, user, emp1.id, d1, _custom_for_worked())
        adj_id_2, _ = _apply_adjustment(db, user, emp2.id, d2, _custom_for_worked())
        db.commit()
    finally:
        db.info.pop("bulk_no_commit", None)

    adj1 = db.get(Adjustment, adj_id_1)
    adj2 = db.get(Adjustment, adj_id_2)
    assert adj1 is not None
    assert adj2 is not None
    assert adj1.outcome == "worked"
    assert adj2.outcome == "worked"

    audits = list(db.scalars(select(AuditLog).where(
        AuditLog.entity_type == "adjustment",
        AuditLog.action == "attendance.adjustment.create",
    )))
    ids_in_audit = {a.entity_id for a in audits}
    assert str(adj1.id) in ids_in_audit
    assert str(adj2.id) in ids_in_audit


# ----------------------------------------------------------------------
# 4. bulk_adjust failure rolls back the whole batch
# ----------------------------------------------------------------------

def test_bulk_adjust_rolls_back_all_on_item_failure(
    db: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulated bulk loop: first item succeeds, second item fails inside
    recompute_day. The whole batch rolls back. No adjustments persist.
    The failure is captured by pytest.raises so the assertions below
    run after the batch has unwound.
    """
    _mk_cal(db, 2024)
    shift = _mk_shift(db)
    user = _mk_user(db)
    emp1 = _mk_employee(db, default_shift_id=shift.id)
    emp2 = _mk_employee(db, default_shift_id=shift.id)
    d1 = date(2024, 5, 15)
    d2 = date(2024, 5, 16)
    _mk_day(db, emp1.id, d1)
    _mk_day(db, emp2.id, d2)
    db.rollback()

    import app.api.v1.exceptions as exc_mod
    original_recompute = exc_mod.recompute_day

    call_count = {"n": 0}
    def _maybe_boom(db_, employee_id, work_date):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated second-item failure")
        return original_recompute(db_, employee_id, work_date)
    monkeypatch.setattr(exc_mod, "recompute_day", _maybe_boom)

    db.info["bulk_no_commit"] = True
    try:
        with pytest.raises(RuntimeError, match="simulated second-item failure"):
            try:
                _apply_adjustment(db, user, emp1.id, d1, _custom_for_worked())
                _apply_adjustment(db, user, emp2.id, d2, _custom_for_worked())
                db.commit()
            except Exception:
                db.rollback()
                raise
    finally:
        db.info.pop("bulk_no_commit", None)

    adj_after = list(db.scalars(select(Adjustment).where(
        Adjustment.employee_id.in_([emp1.id, emp2.id]),
    )))
    assert adj_after == [], "no adjustments must persist after batch rollback"