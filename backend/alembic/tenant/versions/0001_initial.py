"""Initial tenant-database schema (Phase 1A).

Revision ID: ten_0001
Revises:
Create Date: 2024-01-01 00:00:00
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)

    op.create_table(
        "company",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("trading_name", sa.String(200), nullable=True),
        sa.Column("registration_number", sa.String(60), nullable=True),
        sa.Column("tax_number", sa.String(60), nullable=True),
        sa.Column("paye_reference", sa.String(60), nullable=True),
        sa.Column("uif_reference", sa.String(60), nullable=True),
        sa.Column("sdl_reference", sa.String(60), nullable=True),
        sa.Column("coida_reference", sa.String(60), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="ZA"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("default_timezone", sa.String(64), nullable=False, server_default="Africa/Johannesburg"),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "branch",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_branch_code"),
    )

    op.create_table(
        "site",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "branch_id",
            uuid_type,
            sa.ForeignKey("branch.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("site_type", sa.String(20), nullable=False, server_default="site"),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Africa/Johannesburg"),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("geofence_radius_m", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_site_code"),
    )
    op.create_index("ix_site_branch_id", "site", ["branch_id"])

    op.create_table(
        "department",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("parent_id", uuid_type, sa.ForeignKey("department.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_department_code"),
    )

    op.create_table(
        "employee",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("employee_code", sa.String(40), nullable=False),
        sa.Column("first_name", sa.String(120), nullable=False),
        sa.Column("last_name", sa.String(120), nullable=False),
        sa.Column("national_id_encrypted", sa.Text(), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("mobile", sa.String(40), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("hire_date", sa.Date(), nullable=False),
        sa.Column("termination_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("job_title", sa.String(120), nullable=True),
        sa.Column("branch_id", uuid_type, sa.ForeignKey("branch.id", ondelete="SET NULL"), nullable=True),
        sa.Column("site_id", uuid_type, sa.ForeignKey("site.id", ondelete="SET NULL"), nullable=True),
        sa.Column("department_id", uuid_type, sa.ForeignKey("department.id", ondelete="SET NULL"), nullable=True),
        sa.Column("manager_id", uuid_type, sa.ForeignKey("employee.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_type", sa.String(20), nullable=False, server_default="hourly"),
        sa.Column("pay_basis", sa.String(20), nullable=False, server_default="hourly"),
        sa.Column("pay_frequency", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("base_rate", sa.Numeric(18, 6), nullable=True),
        sa.Column("overtime_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("clocks", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("work_pattern_id", uuid_type, nullable=True),
        sa.Column("default_shift_id", uuid_type, nullable=True),
        sa.Column("bank_name", sa.String(120), nullable=True),
        sa.Column("bank_account_number_encrypted", sa.Text(), nullable=True),
        sa.Column("bank_branch_code", sa.String(20), nullable=True),
        sa.Column("account_type", sa.String(40), nullable=True),
        sa.Column("tax_number", sa.String(40), nullable=True),
        sa.Column("medical_aid_dependants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retirement_fund_flags", sa.String(120), nullable=True),
        sa.Column("uif_exempt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("employee_code", name="uq_employee_code"),
    )
    op.create_index("ix_employee_employee_code", "employee", ["employee_code"])
    op.create_index("ix_employee_email", "employee", ["email"])
    op.create_index("ix_employee_site_id", "employee", ["site_id"])
    op.create_index("ix_employee_department_id", "employee", ["department_id"])

    op.create_table(
        "user",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("username", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("employee_id", uuid_type, sa.ForeignKey("employee.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role", sa.String(30), nullable=False, server_default="employee"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("username", name="uq_user_username"),
    )
    op.create_index("ix_user_username", "user", ["username"])

    op.create_table(
        "employee_pay_history",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("employee_id", uuid_type, sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("changed_by", uuid_type, sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", uuid_type, sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_employee_pay_history_employee_id", "employee_pay_history", ["employee_id"])

    op.create_table(
        "user_scope",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", uuid_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_scope_user_id", "user_scope", ["user_id"])
    op.create_index("ix_user_scope_scope_id", "user_scope", ["scope_id"])

    op.create_table(
        "biometric_consent",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("employee_id", uuid_type, sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_text_version", sa.String(40), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("captured_by", uuid_type, sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("method", sa.String(40), nullable=False, server_default="digital"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_biometric_consent_employee_id", "biometric_consent", ["employee_id"])

    op.create_table(
        "biometric_enrolment",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("employee_id", uuid_type, sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("template_encrypted", sa.Text(), nullable=False),
        sa.Column("vendor", sa.String(60), nullable=False),
        sa.Column("template_version", sa.String(40), nullable=False),
        sa.Column("consent_id", uuid_type, sa.ForeignKey("biometric_consent.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_biometric_enrolment_employee_id", "biometric_enrolment", ["employee_id"])

    op.create_table(
        "device",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("site_id", uuid_type, sa.ForeignKey("site.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("device_type", sa.String(30), nullable=False),
        sa.Column("api_key_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="offline"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_punch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allows_code_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_photo_for_code", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("software_version", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_device_site_id", "device", ["site_id"])
    op.create_index("ix_device_api_key_hash", "device", ["api_key_hash"])

    op.create_table(
        "setting",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("key", name="uq_setting_key"),
    )

    op.create_table(
        "notification",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False, server_default="in_app"),
        sa.Column("template", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_user_id", "notification", ["user_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_user_id", uuid_type, sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
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
    op.create_index("ix_audit_log_occurred_at", "audit_log", ["occurred_at"])
    op.create_index("ix_audit_log_request_id", "audit_log", ["request_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update
        BEFORE UPDATE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_delete
        BEFORE DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
        """
    )

    role = _app_role()
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {role}")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    op.drop_table("audit_log")
    op.drop_table("notification")
    op.drop_table("setting")
    op.drop_table("device")
    op.drop_table("biometric_enrolment")
    op.drop_table("biometric_consent")
    op.drop_table("user_scope")
    op.drop_table("employee_pay_history")
    op.drop_table("user")
    op.drop_table("employee")
    op.drop_table("department")
    op.drop_table("site")
    op.drop_table("branch")
    op.drop_table("company")