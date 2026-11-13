"""Stage A focused integration tests: PayPeriod lock protection on
attendance write paths.

Scope of this file in Batch 1: adjustments (single + bulk pre-validation).
Exception resolve / leave / recompute tests land in later batch files.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.attendance import Adjustment, AttendanceDay
from app.db.tenant.models.pay import PayPeriod
from app.services.payroll_period_guard import assert_dates_not_locked


# --- shared fixture: engine-bound session that rolls back ---------------

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


# --- direct guard call through the adjustment pre-validator ------------
# We exercise the guard's presence at the pre-validator boundary by
# calling the same helper the router uses, in the same DB context.
# Endpoint-level tests (with api_client) follow in Batch 1.5 once the
# tenant-fixture path for the HTTP client is confirmed to match.
# For now, prove:
#   1. A locked period covering the date raises day_locked from the
#      helper, without writing.
#   2. An open period does not raise.
#   3. A date with no period does not raise.

def test_pre_validate_rejects_locked_period(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 3, 1), end=date(2024, 3, 31), status="locked")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session, employee_id=uuid.uuid4(), dates=[date(2024, 3, 15)],
        )
    assert exc.value.code == "day_locked"
    assert exc.value.status_code == 409
    assert exc.value.details == {"dates": ["2024-03-15"]}


def test_pre_validate_allows_open_period(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 4, 1), end=date(2024, 4, 30), status="open")
    assert_dates_not_locked(
        db_session, employee_id=uuid.uuid4(), dates=[date(2024, 4, 15)],
    )


def test_pre_validate_allows_no_period(db_session: Session) -> None:
    assert_dates_not_locked(
        db_session, employee_id=uuid.uuid4(), dates=[date(2023, 6, 15)],
    )


def test_pre_validate_locked_overlapping_open_still_blocks(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 5, 1), end=date(2024, 5, 31), status="locked")
    _mk_period(db_session, start=date(2024, 5, 1), end=date(2024, 5, 31), status="open")
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session, employee_id=uuid.uuid4(), dates=[date(2024, 5, 10)],
        )
    assert exc.value.code == "day_locked"


def test_pre_validate_locked_but_day_row_absent_still_blocks(db_session: Session) -> None:
    """The whole point of the guard: a locked period with NO AttendanceDay
    row for the requested date must still reject the write. This is the
    confirmed Batch 2C gap.
    """
    _mk_period(db_session, start=date(2024, 6, 1), end=date(2024, 6, 30), status="locked")
    # No AttendanceDay row inserted. Confirm the guard still fires.
    no_day = db_session.query(AttendanceDay).filter_by(
        employee_id=uuid.uuid4(), work_date=date(2024, 6, 15),
    ).first()
    assert no_day is None
    with pytest.raises(AppError) as exc:
        assert_dates_not_locked(
            db_session, employee_id=uuid.uuid4(), dates=[date(2024, 6, 15)],
        )
    assert exc.value.code == "day_locked"
    assert exc.value.details == {"dates": ["2024-06-15"]}


def test_pre_validate_never_writes_anything(db_session: Session) -> None:
    _mk_period(db_session, start=date(2024, 7, 1), end=date(2024, 7, 31), status="locked")
    before = db_session.query(Adjustment).count()
    with pytest.raises(AppError):
        assert_dates_not_locked(
            db_session, employee_id=uuid.uuid4(), dates=[date(2024, 7, 15)],
        )
    after = db_session.query(Adjustment).count()
    assert before == after