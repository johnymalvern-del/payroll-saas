"""Add source column to employee_pay_history for import provenance.

Revision ID: ten_0011
Revises: ten_0010
Create Date: 2026-10-28 00:00:00

1C.11's import endpoint creates the first EmployeePayHistory row for a new
employee with source="import" (D7 override). Existing rows written by the
1C.10 request/approve flow remain NULL, which is read as "manual". The
column is deliberately a short String, not an enum, so future sources can
be added without a schema migration; the value is only ever set by import
in 1C.11.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ten_0011"
down_revision: Union[str, Sequence[str], None] = "ten_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employee_pay_history",
        sa.Column("source", sa.String(20), nullable=True),
    )
    op.create_index(
        "ix_pay_history_source",
        "employee_pay_history",
        ["source"],
    )


def downgrade() -> None:
    op.drop_index("ix_pay_history_source", table_name="employee_pay_history")
    op.drop_column("employee_pay_history", "source")

# END OF FILE