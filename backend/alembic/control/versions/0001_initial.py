"""Initial control-database schema.

Revision ID: ctl_0001
Revises:
Create Date: 2024-01-01 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ctl_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriber",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(60), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="ZA"),
        sa.Column("status", sa.String(20), nullable=False, server_default="provisioning"),
        sa.Column("provisioning_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("provisioning_error", sa.Text(), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_employee_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tenant_db_name", sa.String(63), nullable=True),
        sa.Column("tenant_schema_version", sa.String(64), nullable=True),
        sa.Column("encryption_key_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_subscriber_slug", "subscriber", ["slug"])

    op.create_table(
        "platform_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(120), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="platform_admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_platform_user_username", "platform_user", ["username"])

    op.create_table(
        "country_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(2), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", "version", name="uq_country_profile_code_version"),
    )
    op.create_index("ix_country_profile_code", "country_profile", ["code"])

    op.create_table(
        "public_holiday",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("country_code", "holiday_date", "name", name="uq_public_holiday_identity"),
    )
    op.create_index("ix_public_holiday_country_code", "public_holiday", ["country_code"])
    op.create_index("ix_public_holiday_date", "public_holiday", ["holiday_date"])

    op.create_table(
        "statutory_table",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("table_key", sa.String(60), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "country_code", "table_key", "tax_year", "version",
            name="uq_statutory_table_identity",
        ),
    )
    op.create_index("ix_statutory_table_country_code", "statutory_table", ["country_code"])
    op.create_index("ix_statutory_table_table_key", "statutory_table", ["table_key"])

    op.create_table(
        "control_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(40), nullable=True),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_control_audit_log_occurred_at", "control_audit_log", ["occurred_at"])
    op.create_index("ix_control_audit_log_request_id", "control_audit_log", ["request_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION control_audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'control_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER control_audit_log_no_update
        BEFORE UPDATE ON control_audit_log
        FOR EACH ROW EXECUTE FUNCTION control_audit_log_immutable();
        """
    )
    op.execute(
        """
        CREATE TRIGGER control_audit_log_no_delete
        BEFORE DELETE ON control_audit_log
        FOR EACH ROW EXECUTE FUNCTION control_audit_log_immutable();
        """
    )

    op.execute("GRANT USAGE ON SCHEMA public TO payroll_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO payroll_app"
    )
    op.execute("REVOKE UPDATE, DELETE ON control_audit_log FROM payroll_app")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS control_audit_log_no_delete ON control_audit_log")
    op.execute("DROP TRIGGER IF EXISTS control_audit_log_no_update ON control_audit_log")
    op.execute("DROP FUNCTION IF EXISTS control_audit_log_immutable()")
    op.drop_table("control_audit_log")
    op.drop_table("statutory_table")
    op.drop_table("public_holiday")
    op.drop_table("country_profile")
    op.drop_table("platform_user")
    op.drop_table("subscriber")