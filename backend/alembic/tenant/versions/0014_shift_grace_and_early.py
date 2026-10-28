"""Chapter 2B amendments B4 and B5: two new shift columns.

Revision ID: ten_0014
Revises: ten_0013
Create Date: 2026-10-28 00:00:00

B4: grace_mode. If 'threshold' (default), a late arrival within grace is
treated as on time; if late beyond grace, lateness counts from the
scheduled start in full. If 'allowance', only the excess beyond grace
counts. Same behaviour for early departure via grace_early_minutes.

B5: pay_early_arrival. If false (default), time before the scheduled
shift start is not paid and the day gets flag early_arrival_ignored. If
true, early minutes count as overtime and follow the shift's
overtime_requires_approval setting.

Both columns are tenant configuration with safe defaults; no data backfill
needed. Existing rows get 'threshold' and false.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ten_0014"
down_revision: Union[str, Sequence[str], None] = "ten_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shift",
        sa.Column("grace_mode", sa.String(20), nullable=False, server_default="threshold"),
    )
    op.add_column(
        "shift",
        sa.Column("pay_early_arrival", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("shift", "pay_early_arrival")
    op.drop_column("shift", "grace_mode")

# END OF FILE
