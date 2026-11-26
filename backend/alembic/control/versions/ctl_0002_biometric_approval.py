"""Biometric approval record (privacy policy section 8).

Revision ID: ctl_0002
Revises: ctl_0001

Section 8 of the biometric privacy policy permits no collection of biometric
data until a signed approval record exists. Until now that was a document on
disk with `status: not_approved` in its header, which is not a control: anyone
with repository write access can change one line, there is no audit trail of
who approved it, and an auditor has no reason to trust a file's git history.

This table is the control. It lives in the CONTROL database, not the tenant
database, deliberately:

  * the approval is per-tenant but must survive independently of that tenant's
    data
  * a tenant administrator must not be able to edit their own approval
  * the retention sweep, which runs against tenant databases, must not be able
    to affect it

record_sha256 is the part that stops the row being a weaker control than the
file was. It holds the SHA-256 of the signed document, and the gate verifies
the two still agree. Without it, someone with control-database write access
could set status='approved' and the gate would open. With it, they would also
have to forge a document whose hash matches -- and the real document's hash is
in version control, so the alteration is detectable afterwards.

That does not make tampering impossible for an insider holding both database
and filesystem access. It makes it detectable, which is what an audit trail is
for.

Scope columns hold tenant-database UUIDs as opaque strings. There is no foreign
key across the control/tenant boundary and there should not be: a scope entry
can only ever RESTRICT access, so an entry referencing a deleted employee
simply stops matching anything. Keeping employee references referentially
consistent across two databases would need a distributed transaction for a
field whose only job is to narrow a permission.

An empty or NULL scope array means "all", matching the natural reading of an
approval that names no exclusions.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ctl_0002"
down_revision = "ctl_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "biometric_approval",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subscriber_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriber.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 'not_approved' | 'approved' | 'revoked'
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="not_approved"
        ),
        # 'fingerprint' | 'face' | 'both'
        sa.Column("biometric_type", sa.String(20), nullable=False),
        sa.Column("approved_by_company", sa.String(200), nullable=True),
        sa.Column("approved_by_counsel", sa.String(200), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        # NULL means no expiry. The policy discourages it -- an approval with no
        # end date is one nobody revisits -- but forbidding it outright would
        # block a legitimate open-ended decision by counsel.
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("record_sha256", sa.String(64), nullable=False),
        sa.Column(
            "scope_employee_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "scope_site_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "row_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "subscriber_id",
            "biometric_type",
            name="uq_biometric_approval_subscriber_type",
        ),
    )
    op.create_index(
        "ix_biometric_approval_subscriber",
        "biometric_approval",
        ["subscriber_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_biometric_approval_subscriber", table_name="biometric_approval")
    op.drop_table("biometric_approval")