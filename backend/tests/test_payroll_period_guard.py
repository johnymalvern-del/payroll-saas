"""Focused unit tests for payroll_period_guard.assert_dates_not_locked."""
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
    """Own session bound to the shared tenant engine.

    Rolls back at the end so any PayPeriod rows the test inserted are
    discarded, regardless of how the test exits. Does not commit.
    """
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
    # period_key is VARCHAR(40). uuid4().hex is 32 chars, fits comfortably.
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


def test_empty_dates_no_op(db_session: Session) -> None:
    assert_dates_not_locked(db_session, employee_id=None, dates=[])
    assert_dates_not_locked(db_session, employee_id=uuid.uuid4(), dates=[])


def test_no_matching_period_allowed(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 1, 1), end=date(2024, 1, 31), status="locked")
    assert_dates_not_locked(db_session, employee_id=None, dates=[date(2023, 12, 15)])


def test_open_period_allowed(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 2, 1), end=date(2024, 2, 29), status="open")
    assert_dates_not_locked(db_session, employee_id=None, dates=[date(2024, 2, 15)])


def test_locked_period_blocks(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 3, 1), end=date(2024, 3, 31), status="locked")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(db_session, employee_id=None, dates=[date(2024, 3, 15)])
    assert exc.value.code == "day_locked"
    assert exc.value.status_code == 409
    assert exc.value.details == {"dates": ["2024-03-15"]}


def test_locked_period_blocks_even_if_other_open_overlaps(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 4, 1), end=date(2024, 4, 30), status="locked")
    _mk_period(db_session, start=date(2024, 4, 1), end=date(2024, 4, 30), status="open")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(db_session, employee_id=None, dates=[date(2024, 4, 10)])
    assert exc.value.code == "day_locked"


def test_all_open_overlaps_allowed(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 5, 1), end=date(2024, 5, 31), status="open")
    _mk_period(db_session, start=date(2024, 6, 1), end=date(2024, 6, 30), status="open")
    assert_dates_not_locked(
        db_session, employee_id=None,
        dates=[date(2024, 5, 20), date(2024, 6, 10)],
    )


def test_multiple_locked_periods_partial_match(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 7, 1), end=date(2024, 7, 31), status="open")
    _mk_period(db_session, start=date(2024, 8, 1), end=date(2024, 8, 31), status="locked")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session,
            employee_id=None,
            dates=[date(2024, 7, 20), date(2024, 8, 10), date(2024, 9, 1)],
        )
    assert exc.value.code == "day_locked"
    assert exc.value.details == {"dates": ["2024-08-10"]}


def test_employee_id_ignored_but_accepted(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 9, 1), end=date(2024, 9, 30), status="locked")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session, employee_id=uuid.uuid4(), dates=[date(2024, 9, 15)]
        )
    assert exc.value.code == "day_locked"