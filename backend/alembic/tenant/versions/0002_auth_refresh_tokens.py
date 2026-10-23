
"""Auth: refresh-token families, individual refresh tokens, user.password_changed_at.

Revision ID: ten_0002
Revises: ten_0001
Create Date: 2026-10-23 00:00:00
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0002"
down_revision: Union[str, Sequence[str], None] = "ten_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "refresh_token_family",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(40), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
    )
    op.create_index(
        "ix_refresh_token_family_user_id", "refresh_token_family", ["user_id"]
    )

    op.create_table(
        "refresh_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_token_family.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jti_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replaced_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_token.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_refresh_token_family_id", "refresh_token", ["family_id"])
    op.create_index("ix_refresh_token_expires_at", "refresh_token", ["expires_at"])

    # --- Grants for the application role --------------------------------
    # The 0001 migration granted payroll_app on ALL TABLES that existed at
    # that moment. New tables created by this migration are not covered by
    # that grant, so we must grant explicitly. Do not skip this.
    role = _app_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_token_family TO {role}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_token TO {role}"
    )
    # Also ensure any future table created by the current migration role
    # in this schema gets the same grant automatically. This protects
    # future migrations that forget to grant.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {role}"
    )


def downgrade() -> None:
    # Revoke default privileges we added (idempotent-safe: use IF EXISTS pattern).
    role = _app_role()
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {role}"
    )
    op.drop_index("ix_refresh_token_expires_at", table_name="refresh_token")
    op.drop_index("ix_refresh_token_family_id", table_name="refresh_token")
    op.drop_table("refresh_token")
    op.drop_index("ix_refresh_token_family_user_id", table_name="refresh_token_family")
    op.drop_table("refresh_token_family")
    op.drop_column("user", "password_changed_at")
