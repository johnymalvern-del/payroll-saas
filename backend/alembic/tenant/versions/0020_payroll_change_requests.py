"""Payroll change request table (Chapter 4, Bundle 004a-iv-a).

Revision ID: ten_0020
Revises: ten_0019
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0020"
down_revision: Union[str, Sequence[str], None] = "ten_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    op.create_table(
        "payroll_change_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("applied_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('employee_earning_create','employee_earning_update',"
            "'employee_earning_deactivate','employee_deduction_create',"
            "'employee_deduction_update','employee_deduction_deactivate',"
            "'employee_field_update')",
            name="ck_payroll_change_request_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled')",
            name="ck_payroll_change_request_status",
        ),
    )
    op.create_index(
        "ix_payroll_change_request_employee_status",
        "payroll_change_request", ["employee_id", "status"],
    )
    op.create_index(
        "ix_payroll_change_request_status",
        "payroll_change_request", ["status"],
    )
    role = _app_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON payroll_change_request TO {role}"
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_change_request_status", table_name="payroll_change_request")
    op.drop_index("ix_payroll_change_request_employee_status", table_name="payroll_change_request")
    op.drop_table("payroll_change_request")

# END OF FILE
