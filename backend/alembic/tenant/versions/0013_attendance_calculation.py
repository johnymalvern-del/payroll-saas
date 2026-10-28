"""Attendance calculation tables plus country calendar.

Revision ID: ten_0013
Revises: ten_0012
Create Date: 2026-10-28 00:00:00

Three new tables:

  attendance_day       one row per (employee, work_date). work_date is the
                       LOCAL date on which the shift STARTS - the day the
                       shift belongs to. A night shift 22:00-06:00 is ONE
                       attendance_day whose segments carry local_date values
                       on two consecutive calendar dates.

  attendance_segment   one row per rate-relevant piece of work. Cut at local
                       midnight, at day-type boundaries, and at rate-tier
                       boundaries. local_date is the real calendar date of
                       this piece; it may differ from the parent day's
                       work_date.

  country_calendar     official country holiday dates loaded from a CSV the
                       user supplies. Unique per (country_code, holiday_date).
                       day-build fails closed with holiday_calendar_missing
                       when a requested year has no rows; a missing calendar
                       is NEVER read as "no holidays".

worked_minutes = normal_minutes + overtime_minutes (paid minutes).
raw_minutes is elapsed time minus unpaid break, before rounding and grace.

source_version increments only when computed output changes (status,
minutes, segments, flags). computed_at updates on every successful
recompute. Phase 4 payslip comparisons use source_version so a no-op
recompute does not look like a change.
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0013"
down_revision: Union[str, Sequence[str], None] = "ten_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    op.create_table(
        "attendance_day",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("first_in", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worked_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("normal_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overtime_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shift_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("shift.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_attendance_day_emp_date", "attendance_day", ["employee_id", "work_date"]
    )
    op.create_index("ix_attendance_day_date", "attendance_day", ["work_date"])
    op.create_index("ix_attendance_day_status", "attendance_day", ["status"])

    op.create_table(
        "attendance_segment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attendance_day_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("attendance_day.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("day_type", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("rate_method", sa.String(20), nullable=False),
        sa.Column("rate_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("overtime_status", sa.String(20), nullable=True),
        sa.Column("source_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_attendance_segment_day", "attendance_segment", ["attendance_day_id"])

    op.create_table(
        "country_calendar",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_country_calendar_code_date", "country_calendar", ["country_code", "holiday_date"]
    )
    op.create_index("ix_country_calendar_date", "country_calendar", ["holiday_date"])

    role = _app_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
        f"attendance_day, attendance_segment, country_calendar TO {role}"
    )


def downgrade() -> None:
    op.drop_index("ix_country_calendar_date", table_name="country_calendar")
    op.drop_table("country_calendar")
    op.drop_index("ix_attendance_segment_day", table_name="attendance_segment")
    op.drop_table("attendance_segment")
    op.drop_index("ix_attendance_day_status", table_name="attendance_day")
    op.drop_index("ix_attendance_day_date", table_name="attendance_day")
    op.drop_table("attendance_day")

# END OF FILE
