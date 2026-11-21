"""Add adjustment.shift_id (nullable FK to shift.id, ON DELETE SET NULL).

Stage B Batch C — shift correction. HR can override the detected shift on
a specific (employee, work_date) by creating an Adjustment with shift_id
set. Existing rows have shift_id = NULL after this migration, which means
"no override" — current behaviour is preserved.

ON DELETE SET NULL: if a Shift row is ever hard-deleted, the adjustment's
shift_id becomes NULL, but the shift's name is preserved in the
adjustment's new_value JSONB snapshot (captured at write time, not read
time). History remains meaningful and auditable after deletion.

Revision ID: ten_0028
Revises: ten_0027
Create Date: 2026-11-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "ten_0028"
down_revision = "ten_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "adjustment",
        sa.Column("shift_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_adjustment_shift_id",
        "adjustment",
        "shift",
        ["shift_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_adjustment_shift_id",
        "adjustment",
        ["shift_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_adjustment_shift_id", table_name="adjustment")
    op.drop_constraint(
        "fk_adjustment_shift_id", "adjustment", type_="foreignkey",
    )
    op.drop_column("adjustment", "shift_id")