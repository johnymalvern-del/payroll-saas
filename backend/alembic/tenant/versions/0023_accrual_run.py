"""Accrual run tracking (Chapter 3, 3B.3, amendment 3).

Adds a single timestamp column so GET /leave/balances can surface
`accrual_stale` when the last run is more than a day old.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ten_0023"
down_revision = "ten_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payroll_settings",
        sa.Column(
            "last_accrual_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("payroll_settings", "last_accrual_run_at")