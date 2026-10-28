"""Attendance models (Chapter 2A).

Seven models matching migration 0012: Shift, ShiftRateRule, WorkPattern,
WorkPatternDay, PublicHolidayTenant, Punch, EmployeeWorkPattern.

Punch is insert-only at the database level (REVOKE UPDATE, DELETE plus a
BEFORE UPDATE OR DELETE trigger installed by migration 0012). The model
therefore has no updated_at column and inherits only Base, not
TimestampMixin. No code path updates or deletes a punch.

Device is NOT declared here. Migration 0001 already created the device
table; the Device model lives in its existing file. Migration 0012 adds
device.row_version and uq_device_api_key_hash, and the Device model will
be updated in a later script to expose row_version.

No __table_args__ unique constraints are declared for the functional
unique index uq_shift_name_lower_active because it is on lower(btrim(name))
WHERE is_active=true, which SQLAlchemy cannot express as a UniqueConstraint.
Uniqueness is enforced by migration 0012 at the DB level.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class Shift(Base, TimestampMixin):
    __tablename__ = "shift"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_time: Mapped[time] = mapped_column(Time(), nullable=False)
    length_minutes: Mapped[int] = mapped_column(Integer(), nullable=False)
    unpaid_break_minutes: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0"
    )
    paid_break_minutes: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0"
    )
    grace_late_minutes: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0"
    )
    grace_early_minutes: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0"
    )
    rounding_minutes: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0"
    )
    rounding_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="nearest", server_default="nearest"
    )
    min_overtime_minutes: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0"
    )
    overtime_requires_approval: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True, server_default=true()
    )
    max_shift_minutes: Mapped[int] = mapped_column(Integer(), nullable=False)
    match_tolerance_minutes: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=60, server_default="60"
    )
    salaried_premium_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="full", server_default="full"
    )
    grace_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="threshold", server_default="threshold"
    )
    pay_early_arrival: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True, server_default=true()
    )
    row_version: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1"
    )


class ShiftRateRule(Base, TimestampMixin):
    __tablename__ = "shift_rate_rule"
    __table_args__ = (
        UniqueConstraint(
            "shift_id", "day_type", "kind", "tier", "effective_from",
            name="uq_srr_key",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shift.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_type: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    tier: Mapped[int] = mapped_column(Integer(), nullable=False)
    tier_up_to_minutes: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    flat_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date(), nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date(), nullable=True)


class WorkPattern(Base, TimestampMixin):
    __tablename__ = "work_pattern"
    __table_args__ = (UniqueConstraint("name", name="uq_work_pattern_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    cycle_length_days: Mapped[int] = mapped_column(Integer(), nullable=False)
    anchor_date: Mapped[date] = mapped_column(Date(), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True, server_default=true()
    )
    row_version: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1"
    )

    days: Mapped[list["WorkPatternDay"]] = relationship("WorkPatternDay", cascade="all, delete-orphan", order_by="WorkPatternDay.day_index")


class WorkPatternDay(Base, TimestampMixin):
    __tablename__ = "work_pattern_day"
    __table_args__ = (
        UniqueConstraint(
            "work_pattern_id", "day_index", name="uq_wpd_pattern_day"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    work_pattern_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_pattern.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    is_expected: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    expected_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shift.id", ondelete="SET NULL"),
        nullable=True,
    )


class PublicHolidayTenant(Base, TimestampMixin):
    __tablename__ = "public_holiday_tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    holiday_date: Mapped[date] = mapped_column(Date(), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site.id", ondelete="CASCADE"),
        nullable=True,
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("department.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_working_day_override: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True, server_default=true()
    )
    row_version: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1"
    )


class Punch(Base):
    """One punch event. Insert-only; never updated or deleted (see module
    docstring). The append-only rule is enforced by migration 0012 and by
    convention in every code path."""

    __tablename__ = "punch"
    __table_args__ = (
        UniqueConstraint(
            "device_id", "client_punch_id", name="uq_punch_device_client"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    client_punch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="RESTRICT"),
        nullable=True,
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site.id", ondelete="RESTRICT"),
        nullable=True,
    )
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    device_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    device_now_at_send: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    offset_ms: Mapped[int] = mapped_column(Integer(), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    match_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    liveness_passed: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    photo_object_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    flags: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        server_default=text("'[]'::jsonb"),
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EmployeeWorkPattern(Base, TimestampMixin):
    __tablename__ = "employee_work_pattern"

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="CASCADE"),
        nullable=False,
    )
    work_pattern_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_pattern.id", ondelete="RESTRICT"),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date(), nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date(), nullable=True)


class AttendanceDay(Base, TimestampMixin):
    """One row per (employee, work_date).

    work_date is the local date on which the shift STARTS - the day the
    shift belongs to. A night shift that runs from 22:00 to 06:00 the next
    morning is ONE AttendanceDay with work_date = the starting date; its
    attendance_segment rows may carry local_date values on two consecutive
    calendar dates. This is deliberate: the day is the shift-start day,
    the segments are the real calendar pieces.

    worked_minutes = normal_minutes + overtime_minutes (paid minutes).
    raw_minutes is elapsed time minus unpaid break, before rounding and
    grace, kept for audit and drill-down.

    source_version increments ONLY when the computed output (status,
    minutes, segments, flags) actually changes. computed_at updates on
    every successful recompute. Phase 4's payslip comparison uses
    source_version, so a no-op recompute must not look like a change.
    """

    __tablename__ = "attendance_day"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_attendance_day_emp_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    work_date: Mapped[date] = mapped_column(Date(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    first_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worked_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    normal_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    overtime_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    raw_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shift.id", ondelete="RESTRICT"),
        nullable=True,
    )
    flags: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    row_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")

    segments: Mapped[list["AttendanceSegment"]] = relationship(
        "AttendanceSegment",
        cascade="all, delete-orphan",
        order_by="AttendanceSegment.local_date, AttendanceSegment.kind, AttendanceSegment.tier",
    )


class AttendanceSegment(Base, TimestampMixin):
    """One rate-relevant piece of work.

    Cut at local midnight, at day-type boundaries, and at rate-tier
    boundaries. local_date is the real calendar date of this segment; it
    may differ from the parent day's work_date on a night shift.

    rate_method and rate_value record the applicable shift_rate_rule at
    build time. A multiplier needs an hourly rate to become money; that
    conversion is Phase 4 and is not done here.
    """

    __tablename__ = "attendance_segment"

    id: Mapped[uuid.UUID] = uuid_pk()
    attendance_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_day.id", ondelete="CASCADE"),
        nullable=False,
    )
    local_date: Mapped[date] = mapped_column(Date(), nullable=False)
    day_type: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    tier: Mapped[int] = mapped_column(Integer(), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer(), nullable=False)
    rate_method: Mapped[str] = mapped_column(String(20), nullable=False)
    rate_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    overtime_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_refs: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


class CountryCalendar(Base, TimestampMixin):
    """Official country holiday dates, loaded from a CSV the user supplies.

    The tenant's country comes from company.country_code (default ZA). The
    loader refuses to load a year twice unless --replace is given. day-build
    raises holiday_calendar_missing if a requested year has no rows for the
    country; a missing calendar is NEVER read as "no holidays".
    """

    __tablename__ = "country_calendar"
    __table_args__ = (
        UniqueConstraint("country_code", "holiday_date", name="uq_country_calendar_code_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date(), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExceptionItem(Base, TimestampMixin):
    """One open exception of each type per (employee, work_date).

    Uniqueness of open rows enforced by partial unique index
    uq_exception_item_open on (employee_id, work_date, type) WHERE status='open'.
    Resolved rows accumulate history; when the underlying condition re-appears
    after being resolved, a new open row is created (C4).
    """

    __tablename__ = "exception_item"

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    work_date: Mapped[date] = mapped_column(Date(), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_ref: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    suggested_fix: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default="open"
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Adjustment(Base):
    """Append-only attendance adjustment (C6). Only created_at, no updated_at.

    The latest active adjustment for a (employee_id, work_date) wins;
    outcome='revert' restores the punch-based computation. Never edited
    or deleted. old_value and new_value capture the attendance_day snapshot
    before and after so audit drill-down shows exactly what changed.
    """

    __tablename__ = "adjustment"

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    work_date: Mapped[date] = mapped_column(Date(), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    time_in: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    time_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    minutes: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

# END OF FILE
