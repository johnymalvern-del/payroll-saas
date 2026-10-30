"""Payroll settings table (Chapter 4, Bundle 003b).

Revision ID: ten_0018
Revises: ten_0017
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0018"
down_revision: Union[str, Sequence[str], None] = "ten_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    op.create_table(
        "payroll_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("age_reference_date", sa.String(20), nullable=True),
        sa.Column("sdl_applies", sa.Boolean(), nullable=True),
        sa.Column("net_pay_floor", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
    )
    role = _app_role()
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON payroll_settings TO {role}")


def downgrade() -> None:
    op.drop_table("payroll_settings")

# END OF FILE
