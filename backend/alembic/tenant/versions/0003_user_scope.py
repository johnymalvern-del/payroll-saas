
"""Add missing constraints to user_scope.

Revision ID: ten_0003
Revises: ten_0002
Create Date: 2026-10-23 00:00:00

Ground truth about user_scope as actually created by 0001_initial.py:

    columns:      id, user_id, scope_type, scope_id, created_at, updated_at
    constraints:  user_scope_pkey (id), user_scope_user_id_fkey (user_id -> user)
    indexes:      ix_user_scope_user_id, ix_user_scope_scope_id

What 0001 did NOT create, and what this migration adds:

    ck_user_scope_scope_type  - CHECK (scope_type IN ('site','branch','department'))
    uq_user_scope_triple      - UNIQUE (user_id, scope_type, scope_id)

The unique constraint is what guarantees that a user is not scoped to the
same site (or branch, or department) twice, which the permission layer
relies on. The check constraint is what guarantees that no scope row can
reference an unknown scope_type.

This migration does NOT create the user_scope table (0001 does), does NOT
create either index (0001 does), and does NOT touch any other table.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "ten_0003"
down_revision: Union[str, Sequence[str], None] = "ten_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_user_scope_scope_type",
        "user_scope",
        "scope_type IN ('site','branch','department')",
    )
    op.create_unique_constraint(
        "uq_user_scope_triple",
        "user_scope",
        ["user_id", "scope_type", "scope_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_scope_triple", "user_scope", type_="unique")
    op.drop_constraint("ck_user_scope_scope_type", "user_scope", type_="check")
