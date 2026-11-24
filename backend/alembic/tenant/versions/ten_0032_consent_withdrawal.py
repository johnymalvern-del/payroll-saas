"""Add withdrawal fields to biometric_consent.

BiometricConsent recorded only that consent was *given*: consent_text_version,
accepted_at, captured_by, method. Nothing recorded that it was later
withdrawn, so withdrawal could not be represented at all without destroying
the row -- which would erase the evidence that consent was ever given, the
opposite of what an audit needs.

Two columns are added rather than deleting the consent row:

  withdrawn_at   when the consent stopped being active
  withdrawn_by   which user recorded the withdrawal (NULL if the employee
                 withdrew through a self-service path that has no user)

The row itself is never deleted. Policy section 2 requires the revocation to
be recorded in an audit trail; the record of what was consented to, and when,
has to survive that.

No unique index on (employee_id) WHERE withdrawn_at IS NULL. Exactly one
active consent per employee is enforced in the API instead, because a unique
index would turn a race between two HR users into a 500 rather than a 409
with a readable message. The API check is adequate for an HR workflow.

Revision ID: ten_0032
Revises: ten_0031
Create Date: 2026-11-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "ten_0032"
down_revision = "ten_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "biometric_consent",
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "biometric_consent",
        sa.Column(
            "withdrawn_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Finding the active consent for an employee is the hottest read on this
    # table; without it every status check is a sequential scan.
    op.create_index(
        "ix_biometric_consent_employee_active",
        "biometric_consent",
        ["employee_id"],
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_biometric_consent_employee_active", table_name="biometric_consent"
    )
    op.drop_column("biometric_consent", "withdrawn_by")
    op.drop_column("biometric_consent", "withdrawn_at")