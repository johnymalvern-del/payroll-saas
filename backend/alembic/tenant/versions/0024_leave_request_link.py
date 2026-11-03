"""Leave request ownership + adjustment link (Chapter 3, 3C amendments 2 & 8).

Adds:
  leave_request.captured_by_user_id   UUID | null FK to user.id
      Records who submitted the request (self-service or HR capture-on-
      behalf). Amendment 8.

  adjustment.leave_request_id         UUID | null FK to leave_request.id
      Links an attendance adjustment back to the leave request that
      created it. Amendment 2.

  adjustment.system_generated         bool not null default false
      Marks adjustments created by a system workflow (leave approval)
      rather than by a user-initiated adjust request. Amendment 2.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ten_0024"
down_revision = "ten_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leave_request",
        sa.Column(
            "captured_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "adjustment",
        sa.Column(
            "leave_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leave_request.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "adjustment",
        sa.Column(
            "system_generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("adjustment", "system_generated")
    op.drop_column("adjustment", "leave_request_id")
    op.drop_column("leave_request", "captured_by_user_id")