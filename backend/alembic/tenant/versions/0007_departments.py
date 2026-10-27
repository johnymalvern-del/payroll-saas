"""Add case-insensitive unique constraint on department.code and parent index.

Revision ID: ten_0007
Revises: ten_0006
Create Date: 2026-10-27 00:00:00

1C.7 requires department codes to be unique per tenant, case-insensitively,
after trimming. 0004 added the case-sensitive `uq_department_code`
constraint; this revision adds the functional unique index on
lower(btrim(code)) so duplicates differing only in letter case or
surrounding whitespace are rejected at the database level. The application
layer also normalises `code` on write and returns 409 duplicate_code.

Also adds ix_department_parent_active on (parent_id, is_active) because
1C.7 lists departments filtered by parent and by active status, and the
deactivate guard reads (parent_id, is_active) when a parent is checked for
active children. Downgrade drops only these two indexes; it does not remove
the 0004 constraint.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "ten_0007"
down_revision: Union[str, Sequence[str], None] = "ten_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_department_code_lower "
        "ON department (lower(btrim(code)))"
    )
    op.create_index(
        "ix_department_parent_active",
        "department",
        ["parent_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_department_parent_active", table_name="department")
    op.execute("DROP INDEX IF EXISTS uq_department_code_lower")

# END OF FILE