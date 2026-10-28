"""Attendance work surface (Chapter 2C).

Revision ID: ten_0015
Revises: ten_0014
Create Date: 2026-10-29 00:00:00

Two new tables plus two new columns on attendance_day.

exception_item: one open exception of each type per (employee, work_date).
Enforced by partial unique index uq_exception_item_open on
(employee_id, work_date, type) WHERE status='open'.

adjustment: append-only (C6). Only created_at, no updated_at. Batch
adjustments share a batch_id; individual ones have NULL batch_id. old_value
and new_value capture the attendance_day snapshot before and after for
audit. period_id is reserved for Phase 4 next-period corrections; 2C
never sets it.

attendance_day.reviewed_at / reviewed_by: set by POST
/attendance/mark_reviewed. Cleared when recompute_day detects a content
change (C3). reviewed_by is nullable because system-triggered clears do
not have a user.
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0015"
down_revision: Union[str, Sequence[str], None] = "ten_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    op.create_table(
        "exception_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("source_ref", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("suggested_fix", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_exception_item_emp_date", "exception_item",
                    ["employee_id", "work_date"])
    op.create_index("ix_exception_item_status_date", "exception_item",
                    ["status", "work_date"])
    op.execute(
        "CREATE UNIQUE INDEX uq_exception_item_open "
        "ON exception_item (employee_id, work_date, type) WHERE status='open'"
    )

    op.create_table(
        "adjustment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("time_in", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(40), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("period_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_adjustment_emp_date", "adjustment",
                    ["employee_id", "work_date"])
    op.create_index("ix_adjustment_batch", "adjustment", ["batch_id"])

    op.add_column("attendance_day",
                  sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attendance_day",
                  sa.Column("reviewed_by", postgresql.UUID(as_uuid=True),
                            sa.ForeignKey("user.id", ondelete="SET NULL"),
                            nullable=True))

    role = _app_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON exception_item, adjustment TO {role}"
    )


def downgrade() -> None:
    op.drop_column("attendance_day", "reviewed_by")
    op.drop_column("attendance_day", "reviewed_at")
    op.drop_index("ix_adjustment_batch", table_name="adjustment")
    op.drop_index("ix_adjustment_emp_date", table_name="adjustment")
    op.drop_table("adjustment")
    op.execute("DROP INDEX IF EXISTS uq_exception_item_open")
    op.drop_index("ix_exception_item_status_date", table_name="exception_item")
    op.drop_index("ix_exception_item_emp_date", table_name="exception_item")
    op.drop_table("exception_item")

# END OF FILE
