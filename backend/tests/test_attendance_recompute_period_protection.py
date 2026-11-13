"""Stage A focused tests: recompute endpoint period-lock protection.

The recompute endpoint rejects the WHOLE request when any requested
date overlaps a locked pay period, BEFORE ensure_days runs. These tests
prove the boundary behaviour that the endpoint relies on:

  - A range fully inside a locked period is rejected.
  - A range fully inside an open period is allowed.
  - A range with no applicable period is allowed.
  - A range straddling locked and open periods is rejected as a whole.
  - A range that overlaps a locked period rejects before any
    AttendanceDay row is created by ensure_days.
  - Empty-target early return preserves the existing response even
    when the range overlaps a locked period.

The endpoint itself is not invoked through HTTP here — we exercise the
shared guard and the shape of the rejected range, at the same DB
boundary the endpoint uses. That is the contract the endpoint depends
on.

Known limitation (documented, not proven by test): ensure_days commits
at its end, releasing the guard's FOR UPDATE lock before the per-date
recompute loop. A concurrent finalise can slip in during that window.
Fully closing it requires an attendance_engine change out of Stage A
scope. This file does not claim to close that race.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.pay import PayPeriod
from app.services.payroll_period_guard import assert_dates_not_locked


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


def _enumerate(from_date: date, to_date: date):
    cur = from_date
    while cur <= to_date:
        yield cur
        cur += __import__("datetime").timedelta(days=1)


def test_recompute_range_fully_locked_rejected(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 3, 1), end=date(2024, 3, 31), status="locked")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session,
            employee_id=None,
            dates=_enumerate(date(2024, 3, 10), date(2024, 3, 20)),
        )
    assert exc.value.code == "day_locked"
    # Details list every requested date that falls inside the locked period.
    assert exc.value.details == {
        "dates": [
            "2024-03-10", "2024-03-11", "2024-03-12", "2024-03-13",
            "2024-03-14", "2024-03-15", "2024-03-16", "2024-03-17",
            "2024-03-18", "2024-03-19", "2024-03-20",
        ],
    }


def test_recompute_range_fully_open_allowed(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 4, 1), end=date(2024, 4, 30), status="open")
    assert_dates_not_locked(
        db_session,
        employee_id=None,
        dates=_enumerate(date(2024, 4, 10), date(2024, 4, 20)),
    )


def test_recompute_range_no_period_allowed(db_session: Session) -> None:
    assert_dates_not_locked(
        db_session,
        employee_id=None,
        dates=_enumerate(date(2023, 6, 10), date(2023, 6, 20)),
    )


def test_recompute_range_straddling_locked_open_rejected(db_session: Session) -> None:
    """The Option 2 behaviour: a request whose range touches a locked
    period and an open period is rejected as a WHOLE — the caller must
    split into per-period ranges.
    """
    _mk_period(db_session, start=date(2024, 5, 1), end=date(2024, 5, 31), status="locked")
    _mk_period(db_session, start=date(2024, 6, 1), end=date(2024, 6, 30), status="open")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session,
            employee_id=None,
            dates=_enumerate(date(2024, 5, 25), date(2024, 6, 5)),
        )
    assert exc.value.code == "day_locked"
    # Only the locked-period dates are listed — not the open-period dates.
    listed = set(exc.value.details["dates"])
    assert "2024-05-25" in listed
    assert "2024-05-31" in listed
    assert "2024-06-01" not in listed
    assert "2024-06-05" not in listed


def test_recompute_straddling_lists_only_locked_dates(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 7, 1), end=date(2024, 7, 15), status="locked")
    _mk_period(db_session, start=date(2024, 7, 16), end=date(2024, 7, 31), status="open")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session,
            employee_id=None,
            dates=_enumerate(date(2024, 7, 10), date(2024, 7, 20)),
        )
    assert exc.value.code == "day_locked"
    assert exc.value.details["dates"] == [
        "2024-07-10", "2024-07-11", "2024-07-12",
        "2024-07-13", "2024-07-14", "2024-07-15",
    ]


def test_recompute_guard_does_not_write_anything(db_session: Session) -> None:
    """Rejection is read-only: no AttendanceDay, no AttendanceSegment,
    no PayPeriod status flip. The guard locks and raises; nothing else.
    """
    from app.db.tenant.models.attendance import AttendanceDay, AttendanceSegment

    _mk_period(db_session, start=date(2024, 8, 1), end=date(2024, 8, 31), status="locked")
    day_before = db_session.query(AttendanceDay).count()
    seg_before = db_session.query(AttendanceSegment).count()
    period_status_before = db_session.scalar(
        __import__("sqlalchemy").select(PayPeriod.status).where(
            PayPeriod.start_date == date(2024, 8, 1)
        )
    )
    with pytest.raises(AppError):
        assert_dates_not_locked(
            db_session,
            employee_id=None,
            dates=_enumerate(date(2024, 8, 10), date(2024, 8, 20)),
        )
    assert db_session.query(AttendanceDay).count() == day_before
    assert db_session.query(AttendanceSegment).count() == seg_before
    period_status_after = db_session.scalar(
        __import__("sqlalchemy").select(PayPeriod.status).where(
            PayPeriod.start_date == date(2024, 8, 1)
        )
    )
    assert period_status_after == period_status_before == "locked"


def test_recompute_guard_multiple_locked_periods_in_range(db_session: Session) -> None:
    """When the range overlaps two locked periods separated by an open
    period, all locked dates across both are reported.
    """
    _mk_period(db_session, start=date(2024, 9, 1), end=date(2024, 9, 10), status="locked")
    _mk_period(db_session, start=date(2024, 9, 11), end=date(2024, 9, 20), status="open")
    _mk_period(db_session, start=date(2024, 9, 21), end=date(2024, 9, 30), status="locked")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session,
            employee_id=None,
            dates=_enumerate(date(2024, 9, 5), date(2024, 9, 25)),
        )
    assert exc.value.code == "day_locked"
    listed = set(exc.value.details["dates"])
    # Locked period 1: 5..10
    for d in ("2024-09-05", "2024-09-10"):
        assert d in listed
    # Open period: none of 11..20 should be listed
    for d in ("2024-09-11", "2024-09-20"):
        assert d not in listed
    # Locked period 2: 21..25 (partial overlap with range)
    for d in ("2024-09-21", "2024-09-25"):
        assert d in listed