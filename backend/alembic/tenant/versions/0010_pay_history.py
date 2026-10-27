"""Add decision columns, note, and indexes to employee_pay_history.

Revision ID: ten_0010
Revises: ten_0009
Create Date: 2026-10-27 00:00:00

1C.10 introduces the pay-rate-change approval flow. The 0001 schema for
employee_pay_history has: id, employee_id, base_rate, effective_from,
changed_by, approved_by, status. It has no way to record a rejection, a
decision timestamp, or the requester's note, and no index to enforce
"one live (pending or approved) rate per employee per effective_from".

This revision adds:
  * note            - requester's optional note (1C.10 D3 create body)
  * decided_by      - approver or rejecter (1C.10 D2B); separate from
                      approved_by, which stays reserved for approvals only
  * decided_at      - timestamp of the decision
  * decision_reason - rejection reason (mandatory on reject in the API)

Indexes:
  * uq_pay_history_emp_effective_live
        UNIQUE (employee_id, effective_from)
        WHERE status IN ('pending', 'approved')
    Enforces 1C.10 D6A: no two live rows may share the same effective_from
    for an employee. Rejected and (future) cancelled rows are excluded, so
    a resubmission after a rejection is allowed with the same date.
  * ix_pay_history_emp_effective
        (employee_id, effective_from DESC)
    For "latest rate for employee" queries.
  * ix_pay_history_status
        (status)
    For the approver queue.

The status value 'cancelled' is reserved by 1C.10 but not written by any
endpoint in this phase; it is excluded from the unique index so that a
future cancel endpoint can release the effective_from without a migration.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0010"
down_revision: Union[str, Sequence[str], None] = "ten_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employee_pay_history",
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.add_column(
        "employee_pay_history",
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "employee_pay_history",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employee_pay_history",
        sa.Column("decision_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_employee_pay_history_decided_by",
        "employee_pay_history",
        "user",
        ["decided_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pay_history_emp_effective_live "
        "ON employee_pay_history (employee_id, effective_from) "
        "WHERE status IN ('pending', 'approved')"
    )
    op.execute(
        "CREATE INDEX ix_pay_history_emp_effective "
        "ON employee_pay_history (employee_id, effective_from DESC)"
    )
    op.create_index(
        "ix_pay_history_status",
        "employee_pay_history",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_pay_history_status", table_name="employee_pay_history")
    op.execute("DROP INDEX IF EXISTS ix_pay_history_emp_effective")
    op.execute("DROP INDEX IF EXISTS uq_pay_history_emp_effective_live")
    op.drop_constraint(
        "fk_employee_pay_history_decided_by",
        "employee_pay_history",
        type_="foreignkey",
    )
    op.drop_column("employee_pay_history", "decision_reason")
    op.drop_column("employee_pay_history", "decided_at")
    op.drop_column("employee_pay_history", "decided_by")
    op.drop_column("employee_pay_history", "note")

# END OF FILE