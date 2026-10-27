"""Add case-insensitive unique constraint on branch.code.

Revision ID: ten_0005
Revises: ten_0004
Create Date: 2026-10-26 00:00:00

1C.5 requires branch codes to be unique per tenant, case-insensitively,
after trimming. The 0004 migration added `uq_branch_code` (case-sensitive,
byte-exact), which does not reject "HQ" versus "hq". This revision adds a
functional unique index on lower(btrim(code)) so that duplicates differing
only in letter case or surrounding whitespace are rejected at the database
level. The application layer also checks and returns a clean 409
`duplicate_code`, but the index is the last line of defence.

Downgrade drops only the functional index; it does not remove the
case-sensitive constraint added by 0004 (that belongs to that revision).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "ten_0005"
down_revision: Union[str, Sequence[str], None] = "ten_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_branch_code_lower "
        "ON branch (lower(btrim(code)))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_branch_code_lower")