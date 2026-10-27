"""Add row_version to employee, case-insensitive employee_code index, and
termination_date index.

Revision ID: ten_0008
Revises: ten_0007
Create Date: 2026-10-27 00:00:00

1C.8 requires employee PATCH to use row_version for optimistic concurrency,
matching Company, Branch, Site and Department. 1C.8 also requires
employee_code to be unique per tenant case-insensitively after trimming.
The 0001 schema created `uq_employee_code` (case-sensitive, byte-exact);
this revision adds the functional unique index on lower(btrim(employee_code))
so that duplicates differing only in letter case or surrounding whitespace
are rejected at the database level. The application layer also normalises
the code on write and returns 409 duplicate_code.

Adds ix_employee_termination_date because the employees list defaults to
hiding terminated rows and filters by termination_date when it does not.
Downgrade drops all three; it does not remove the 0001 constraint.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ten_0008"
down_revision: Union[str, Sequence[str], None] = "ten_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employee",
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_employee_code_lower "
        "ON employee (lower(btrim(employee_code)))"
    )
    op.create_index(
        "ix_employee_termination_date",
        "employee",
        ["termination_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_employee_termination_date", table_name="employee")
    op.execute("DROP INDEX IF EXISTS uq_employee_code_lower")
    op.drop_column("employee", "row_version")

# END OF FILE