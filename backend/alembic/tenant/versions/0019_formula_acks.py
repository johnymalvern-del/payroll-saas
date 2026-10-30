"""Formula acknowledgements (Chapter 4, Bundle 004a-i).

Revision ID: ten_0019
Revises: ten_0018

Adds formula_acks JSONB to payroll_settings. Used by F8: readiness screen
warns until each formula is acknowledged; first finalise per tenant refuses
until all acknowledged.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0019"
down_revision: Union[str, Sequence[str], None] = "ten_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payroll_settings",
        sa.Column(
            "formula_acks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("payroll_settings", "formula_acks")

# END OF FILE
