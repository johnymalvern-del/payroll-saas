"""Payroll schema (Chapter 4, Bundle 002).

Revision ID: ten_0017
Revises: ten_0016

Adds three employee columns (idempotent ALTER if missing) and eleven tables.
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0017"
down_revision: Union[str, Sequence[str], None] = "ten_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Employee columns (idempotent)
    cols = {r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='employee'"
    ))}
    for col, ddl in (
        ("contracted_weekly_hours", "NUMERIC(5,2)"),
        ("medical_scheme_members", "INTEGER NOT NULL DEFAULT 0"),
        ("uif_exempt", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ):
        if col not in cols:
            op.execute(f"ALTER TABLE employee ADD COLUMN {col} {ddl}")

    # 2. Tables (in FK-dependency order)
    op.create_table(
        "earning_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("calc_method", sa.String(30), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("is_taxable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("counts_for_uif", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("counts_for_sdl", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("ledger_account", sa.String(40), nullable=True),
        sa.Column("proration_rule", sa.String(30), nullable=False, server_default="none"),
        sa.Column("eligibility_rule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_earning_type_code"),
    )

    op.create_table(
        "deduction_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_pre_tax", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_deduction_type_code"),
    )

    op.create_table(
        "pay_period",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("period_key", sa.String(40), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("period_key", name="uq_pay_period_key"),
    )

    op.create_table(
        "employee_earning",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("earning_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("earning_type.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount IS NOT NULL OR rate IS NOT NULL", name="ck_employee_earning_amount_or_rate"),
    )

    op.create_table(
        "employee_deduction",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deduction_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("deduction_type.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "period_reopen_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pay_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pay_period.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reopened_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("prior_revision", sa.Integer(), nullable=False),
        sa.Column("new_revision", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "period_adjustment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("origin_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pay_period.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pay_period.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("amount_or_minutes", sa.Numeric(14, 4), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("consumed_by_payslip_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        "payroll_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pay_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pay_period.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("rules_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
    )

    op.create_table(
        "payslip",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payroll_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pay_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pay_period.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="current"),
        sa.Column("gross", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("pre_tax_deductions", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("taxable_income", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("paye", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("uif_employee", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("uif_employer", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("sdl", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("other_deductions", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("reimbursements", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("net", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("employer_costs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calculation_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pdf_object_key", sa.String(400), nullable=True),
        sa.Column("predecessor_payslip_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payslip.id", ondelete="SET NULL"), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("computed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("pay_period_id", "employee_id", "revision", name="uq_payslip_period_employee_rev"),
    )

    op.create_table(
        "payslip_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payslip_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payslip.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_type", sa.String(30), nullable=False),
        sa.Column("step", sa.String(20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("units", sa.Numeric(10, 4), nullable=True),
        sa.Column("unit_type", sa.String(20), nullable=True),
        sa.Column("base_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("source_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_payslip_line_payslip", "payslip_line", ["payslip_id"])

    op.create_table(
        "advance_repayment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payslip_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payslip_line.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("advance_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("applied_date", sa.Date(), nullable=False),
        sa.Column("is_deferred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 3. Grants
    role = _app_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
        f"earning_type, deduction_type, employee_earning, employee_deduction, "
        f"pay_period, period_reopen_log, period_adjustment, payroll_run, "
        f"payslip, payslip_line, advance_repayment "
        f"TO {role}"
    )


def downgrade() -> None:
    for t in (
        "advance_repayment", "payslip_line", "payslip", "payroll_run",
        "period_adjustment", "period_reopen_log", "pay_period",
        "employee_deduction", "employee_earning", "deduction_type", "earning_type",
    ):
        op.drop_table(t)
    for col in ("contracted_weekly_hours", "medical_scheme_members", "uif_exempt"):
        op.execute(f"ALTER TABLE employee DROP COLUMN IF EXISTS {col}")

# END OF FILE
