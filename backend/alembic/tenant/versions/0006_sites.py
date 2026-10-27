"""Add case-insensitive unique constraint on site.code and branch index.

Revision ID: ten_0006
Revises: ten_0005
Create Date: 2026-10-27 00:00:00

1C.6 requires site codes to be unique per tenant, case-insensitively, after
trimming. 0004 added the case-sensitive `uq_site_code` constraint; this
revision adds the functional unique index on lower(btrim(code)) so that
duplicates differing only in letter case or surrounding whitespace are
rejected at the database level. The application layer also normalises
`code` on write and returns 409 duplicate_code; the index is the last line
of defence.

Also adds ix_site_branch_active on (branch_id, is_active) because 1C.6
lists sites filtered by branch and by active status, and because the site
deactivation guard reads (branch_id, is_active) when a branch is
reactivated. Downgrade drops only these two indexes; it does not remove
the 0004 constraint.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "ten_0006"
down_revision: Union[str, Sequence[str], None] = "ten_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_site_code_lower "
        "ON site (lower(btrim(code)))"
    )
    op.create_index(
        "ix_site_branch_active",
        "site",
        ["branch_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_branch_active", table_name="site")
    op.execute("DROP INDEX IF EXISTS uq_site_code_lower")

# END OF FILE