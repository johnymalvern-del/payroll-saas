"""Adjustment history endpoint tests (Stage B Batch B).

Focused tests for GET /attendance/adjustments/history:
  1. Filters by employee_id and work_date.
  2. Resolves created_by_name from User; handles missing user gracefully.
  3. Returns newest-first with old_value / new_value snapshots intact.
  4. Enforces scope: an employee user cannot read another employee's
     history (the same assert_in_scope path HR-facing endpoints use).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.api.v1.adjustments import get_adjustment_history
from app.core.errors import AppError
from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import Adjustment, AttendanceDay
from app.db.tenant.models.people import Employee, User
from app.db.tenant.session import get_tenant_engine
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    slug = f"adjh-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="AdjHistory Test",
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


def _mk_user(db: Session, *, role: str, username: str,
             first_name: str | None = None,
             last_name: str | None = None,
             employee_id: uuid.UUID | None = None) -> User:
    u = User(
        username=normalise_username(username),
        password_hash=hash_password("TestPassword123!"),
        role=role,
        is_active=True,
        must_change_password=False,
        employee_id=employee_id,
        row_version=1,
    )
    if first_name is not None:
        setattr(u, "first_name", first_name)
    if last_name is not None:
        setattr(u, "last_name", last_name)
    db.add(u)
    db.commit()
    return u


def _mk_emp(db: Session, code: str) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="Test",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
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


def _mk_adjustment(
    db: Session,
    *,
    employee_id: uuid.UUID,
    work_date: date,
    outcome: str = "worked",
    reason_code: str = "system_correction",
    note: str | None = None,
    created_by: uuid.UUID | None = None,
    created_at: datetime | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> Adjustment:
    a = Adjustment(
        employee_id=employee_id,
        work_date=work_date,
        outcome=outcome,
        time_in=None,
        time_out=None,
        minutes=None,
        reason_code=reason_code,
        note=note,
        batch_id=None,
        created_by=created_by,
        old_value=old_value,
        new_value=new_value,
        period_id=None,
        system_generated=False,
    )
    if created_at is not None:
        a.created_at = created_at
    db.add(a)
    db.commit()
    return a


def _hr_user(db: Session) -> User:
    return _mk_user(db, role="hr", username="hist-hr",
                    first_name="Hist", last_name="HR")


# ----------------------------------------------------------------------
# 1. Filters by employee_id and work_date
# ----------------------------------------------------------------------

def test_history_filters_by_employee_and_date(db: Session) -> None:
    emp1 = _mk_emp(db, "H1")
    emp2 = _mk_emp(db, "H2")
    hr = _hr_user(db)
    d_a = date(2024, 5, 1)
    d_b = date(2024, 5, 2)

    _mk_adjustment(db, employee_id=emp1.id, work_date=d_a, created_by=hr.id)
    _mk_adjustment(db, employee_id=emp1.id, work_date=d_b, created_by=hr.id)
    _mk_adjustment(db, employee_id=emp2.id, work_date=d_a, created_by=hr.id)

    result = get_adjustment_history(
        db=db, user=hr, employee_id=emp1.id, work_date=d_a,
    )
    assert len(result.items) == 1
    assert result.items[0].employee_id == emp1.id
    assert result.items[0].work_date == d_a


# ----------------------------------------------------------------------
# 2. Creator name resolved; missing user handled
# ----------------------------------------------------------------------

def test_history_resolves_creator_name_and_handles_missing_user(db: Session) -> None:
    emp = _mk_emp(db, "H3")
    hr = _hr_user(db)
    d = date(2024, 5, 3)

    _mk_adjustment(db, employee_id=emp.id, work_date=d, created_by=hr.id)

    ghost_user = _mk_user(db, role="hr", username="ghost-hr",
                          first_name="Ghost", last_name="User")
    ghost_id = ghost_user.id
    _mk_adjustment(db, employee_id=emp.id, work_date=d, created_by=ghost_id,
                   note="from a since-deleted user")
    db.delete(ghost_user)
    db.commit()

    result = get_adjustment_history(
        db=db, user=hr, employee_id=emp.id, work_date=d,
    )
    assert len(result.items) == 2
    # Newest first
    assert result.items[0].created_by is None
    assert result.items[0].created_by_name is None
    assert result.items[1].created_by == hr.id
    assert result.items[1].created_by_name is not None
    assert "Hist" in result.items[1].created_by_name


# ----------------------------------------------------------------------
# 3. Newest first + snapshots intact
# ----------------------------------------------------------------------

def test_history_ordered_desc_with_snapshots(db: Session) -> None:
    emp = _mk_emp(db, "H4")
    hr = _hr_user(db)
    d = date(2024, 5, 4)
    _mk_day(db, emp.id, d)

    snap_before = {
        "id": str(uuid.uuid4()),
        "status": "absent",
        "worked_minutes": 0,
        "flags": [],
        "source_version": 0,
        "locked": False,
    }
    snap_after = {
        "id": str(uuid.uuid4()),
        "status": "worked",
        "worked_minutes": 480,
        "flags": [],
        "source_version": 1,
        "locked": False,
    }

    earlier = datetime(2024, 5, 4, 10, 0, tzinfo=timezone.utc)
    later = datetime(2024, 5, 4, 11, 0, tzinfo=timezone.utc)
    _mk_adjustment(
        db, employee_id=emp.id, work_date=d, created_by=hr.id,
        created_at=earlier,
        old_value=snap_before,
        new_value={"day": snap_after, "adjustment": {"id": "a1"}},
    )
    _mk_adjustment(
        db, employee_id=emp.id, work_date=d, created_by=hr.id,
        created_at=later,
        old_value=snap_after,
        new_value={"day": snap_after, "adjustment": {"id": "a2"}},
    )

    result = get_adjustment_history(
        db=db, user=hr, employee_id=emp.id, work_date=d,
    )
    assert len(result.items) == 2
    assert result.items[0].created_at == later
    assert result.items[1].created_at == earlier
    assert result.items[0].old_value == snap_after
    assert result.items[1].old_value == snap_before
    assert result.items[0].new_value is not None
    assert result.items[0].new_value["day"] == snap_after


# ----------------------------------------------------------------------
# 4. Scope enforcement via assert_in_scope
# ----------------------------------------------------------------------

def test_history_rejects_out_of_scope_employee(db: Session) -> None:
    """An employee user cannot read another employee's history.

    The employee role is scoped to own records only (see
    app/core/scope.py). When emp_reader (an employee user linked to
    emp_reader) tries to read emp_other's history, assert_in_scope
    raises ScopeViolation, and the endpoint returns 404 record_not_found
    — the same IDOR-safe pattern the day-detail endpoint uses.

    A positive control (same user, own history) confirms the endpoint is
    not over-restrictive.
    """
    emp_reader = _mk_emp(db, "READER")
    emp_other = _mk_emp(db, "OTHER")
    emp_user = _mk_user(
        db,
        role="employee",
        username="hist-self",
        first_name="Self",
        last_name="Reader",
        employee_id=emp_reader.id,
    )
    d = date(2024, 5, 5)

    # Positive control: reader can see their own history (empty list,
    # no exception raised).
    own = get_adjustment_history(
        db=db, user=emp_user, employee_id=emp_reader.id, work_date=d,
    )
    assert own.items == []

    # Cross-employee read: rejected with record_not_found.
    with pytest.raises(AppError) as exc:
        get_adjustment_history(
            db=db, user=emp_user, employee_id=emp_other.id, work_date=d,
        )
    assert exc.value.code == "record_not_found"
    assert exc.value.status_code == 404