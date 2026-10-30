"""Leave and requests tables (Chapter 3, 3A).

Revision ID: ten_0016
Revises: ten_0015
Create Date: 2026-10-29 00:00:00

Nine tables. leave_balance_ledger is append-only: REVOKE UPDATE, DELETE
from the app role, plus a BEFORE UPDATE OR DELETE trigger for the
superuser path (same belt-and-braces pattern as audit_log and punch).
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0016"
down_revision: Union[str, Sequence[str], None] = "ten_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    # leave_type
    op.create_table(
        "leave_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("paid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("accrual_method", sa.String(20), nullable=False),
        sa.Column("accrual_amount", sa.Numeric(10, 4), nullable=True),
        sa.Column("cycle", sa.String(20), nullable=False, server_default="calendar"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("requires_document_after_days", sa.Integer(), nullable=True),
        sa.Column("allow_negative", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("max_carryover", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_leave_type_code"),
    )

    # leave_balance
    op.create_table(
        "leave_balance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("leave_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("leave_type.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cycle_start", sa.Date(), nullable=False),
        sa.Column("cycle_end", sa.Date(), nullable=False),
        sa.Column("entitled", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("accrued", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("taken", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("pending", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("carried_in", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("adjusted", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("employee_id", "leave_type_id", "cycle_start",
                            name="uq_leave_balance_scope"),
    )
    op.create_index("ix_leave_balance_emp_type", "leave_balance",
                    ["employee_id", "leave_type_id"])

    # leave_balance_ledger (append-only)
    op.create_table(
        "leave_balance_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("leave_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("leave_type.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("delta", sa.Numeric(10, 4), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_leave_balance_ledger_emp_type", "leave_balance_ledger",
                    ["employee_id", "leave_type_id"])
    op.create_index("ix_leave_balance_ledger_ref", "leave_balance_ledger",
                    ["reference_id"])

    # leave_request
    op.create_table(
        "leave_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("leave_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("leave_type.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("days_requested", sa.Numeric(6, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("from_date <= to_date", name="ck_leave_request_dates"),
        sa.CheckConstraint("days_requested > 0", name="ck_leave_request_days_positive"),
    )
    op.create_index("ix_leave_request_emp_status", "leave_request",
                    ["employee_id", "status"])

    # leave_request_day
    op.create_table(
        "leave_request_day",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("leave_request_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("leave_request.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Numeric(6, 2), nullable=False),
        sa.UniqueConstraint("leave_request_id", "work_date", name="uq_leave_request_day"),
        sa.CheckConstraint("days > 0", name="ck_leave_request_day_positive"),
    )

    # leave_approval_step
    op.create_table(
        "leave_approval_step",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("leave_request_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("leave_request.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approver_role", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_leave_approval_step_request", "leave_approval_step",
                    ["leave_request_id"])

    # leave_attachment
    op.create_table(
        "leave_attachment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("leave_request_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("leave_request.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(400), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("virus_scan_status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.create_index("ix_leave_attachment_request", "leave_attachment",
                    ["leave_request_id"])

    # advance_request
    op.create_table(
        "advance_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("repayment_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_advance_request_emp_status", "advance_request",
                    ["employee_id", "status"])

    # grievance
    op.create_table(
        "grievance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reporter_employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_grievance_reporter", "grievance", ["reporter_employee_id"])

    # Grants + append-only ledger
    role = _app_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
        f"leave_type, leave_balance, leave_balance_ledger, leave_request, "
        f"leave_request_day, leave_approval_step, leave_attachment, "
        f"advance_request, grievance "
        f"TO {role}"
    )
    op.execute(f"REVOKE UPDATE, DELETE ON leave_balance_ledger FROM {role}")
    op.execute(
        "CREATE OR REPLACE FUNCTION leave_balance_ledger_append_only() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "  RAISE EXCEPTION 'leave_balance_ledger is append-only'; "
        "END; "
        "$$"
    )
    op.execute(
        "CREATE TRIGGER leave_balance_ledger_no_update_delete "
        "BEFORE UPDATE OR DELETE ON leave_balance_ledger "
        "FOR EACH ROW EXECUTE FUNCTION leave_balance_ledger_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS leave_balance_ledger_no_update_delete ON leave_balance_ledger")
    op.execute("DROP FUNCTION IF EXISTS leave_balance_ledger_append_only()")
    op.drop_index("ix_grievance_reporter", table_name="grievance")
    op.drop_table("grievance")
    op.drop_index("ix_advance_request_emp_status", table_name="advance_request")
    op.drop_table("advance_request")
    op.drop_index("ix_leave_attachment_request", table_name="leave_attachment")
    op.drop_table("leave_attachment")
    op.drop_index("ix_leave_approval_step_request", table_name="leave_approval_step")
    op.drop_table("leave_approval_step")
    op.drop_table("leave_request_day")
    op.drop_index("ix_leave_request_emp_status", table_name="leave_request")
    op.drop_table("leave_request")
    op.drop_index("ix_leave_balance_ledger_ref", table_name="leave_balance_ledger")
    op.drop_index("ix_leave_balance_ledger_emp_type", table_name="leave_balance_ledger")
    op.drop_table("leave_balance_ledger")
    op.drop_index("ix_leave_balance_emp_type", table_name="leave_balance")
    op.drop_table("leave_balance")
    op.drop_table("leave_type")

# END OF FILE
