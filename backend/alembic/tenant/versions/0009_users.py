"""Add row_version to user, plus indexes for the list and the one-active-
user-per-employee rule.

Revision ID: ten_0009
Revises: ten_0008
Create Date: 2026-10-27 00:00:00

1C.9 requires user PATCH to use row_version for optimistic concurrency,
matching Company, Branch, Site, Department, Employee. 1C.9 also enforces
"one active user per employee" with a partial unique index. Two non-unique
indexes support the user list: by role + active, and by employee + active.

"user" is a reserved word in PostgreSQL, so the DDL is issued via
op.execute with explicit quoting rather than op.add_column / op.create_index.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "ten_0009"
down_revision: Union[str, Sequence[str], None] = "ten_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE "user" ADD COLUMN row_version integer NOT NULL DEFAULT 1'
    )
    op.execute(
        'CREATE INDEX ix_user_role_active ON "user" (role, is_active)'
    )
    op.execute(
        'CREATE INDEX ix_user_employee_active ON "user" (employee_id, is_active)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_user_employee_active '
        'ON "user" (employee_id) '
        'WHERE is_active = true AND employee_id IS NOT NULL'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS uq_user_employee_active')
    op.execute('DROP INDEX IF EXISTS ix_user_employee_active')
    op.execute('DROP INDEX IF EXISTS ix_user_role_active')
    op.execute('ALTER TABLE "user" DROP COLUMN row_version')

# END OF FILE