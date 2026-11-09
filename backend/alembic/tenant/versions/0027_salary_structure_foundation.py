"""Salary structure foundation (Milestone 3, Stage A).

Additive only. No existing column dropped. No existing table renamed.

New tables:
  * salary_structure
  * salary_structure_component
  * employee_salary_structure_assignment
  * employee_salary_structure_assignment_attempt

Additive columns:
  * employee_earning.source_assignment_id        -> RESTRICT
  * employee_deduction.source_assignment_id      -> RESTRICT
  * employee_pay_history.source_assignment_id    -> RESTRICT
  * payroll_change_request.assignment_id         -> RESTRICT
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "ten_0027"
down_revision = "ten_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- salary_structure ----------
    op.create_table(
        "salary_structure",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("structure_group_id", postgresql.UUID(as_uuid=True),
                  nullable=False, index=True),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("is_current", sa.Boolean, nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("pay_basis", sa.String(20), nullable=False),
        sa.Column("base_rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False,
                  server_default=sa.text("TRUE")),
        sa.Column("row_version", sa.Integer, nullable=False,
                  server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "structure_group_id", "version_number",
            name="uq_salary_structure_group_version",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_salary_structure_version_positive",
        ),
        sa.CheckConstraint(
            "pay_basis IN ('hourly','daily','monthly')",
            name="ck_salary_structure_pay_basis",
        ),
    )
    op.create_index(
        "uq_salary_structure_current",
        "salary_structure", ["structure_group_id"],
        unique=True, postgresql_where=sa.text("is_current = TRUE"),
    )

    # ---------- salary_structure_component ----------
    op.create_table(
        "salary_structure_component",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "structure_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("salary_structure.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "earning_type_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("earning_type.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "deduction_type_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("deduction_type.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("row_version", sa.Integer, nullable=False,
                  server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('earning','deduction')",
            name="ck_salary_structure_component_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'earning' AND earning_type_id IS NOT NULL AND deduction_type_id IS NULL) "
            "OR (kind = 'deduction' AND deduction_type_id IS NOT NULL AND earning_type_id IS NULL)",
            name="ck_salary_structure_component_type_exclusive",
        ),
        sa.CheckConstraint(
            "(kind = 'deduction' AND amount IS NOT NULL AND rate IS NULL) "
            "OR (kind = 'earning' AND ((amount IS NULL) <> (rate IS NULL)))",
            name="ck_salary_structure_component_amount_or_rate",
        ),
    )

    # ---------- employee_salary_structure_assignment ----------
    op.create_table(
        "employee_salary_structure_assignment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "structure_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("salary_structure.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column(
            "submitted_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column(
            "decided_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text, nullable=True),
        sa.Column("failure_detail", sa.Text, nullable=True),
        sa.Column("override_manual_ids", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("row_version", sa.Integer, nullable=False,
                  server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled')",
            name="ck_assignment_status",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_assignment_effective_range",
        ),
    )
    op.create_index(
        "uq_pending_assignment_per_employee",
        "employee_salary_structure_assignment", ["employee_id"],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_open_approved_assignment",
        "employee_salary_structure_assignment", ["employee_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'approved' AND effective_to IS NULL"
        ),
    )
    op.create_index(
        "uq_assignment_idempotency",
        "employee_salary_structure_assignment", ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_assignment_employee_submitted",
        "employee_salary_structure_assignment",
        ["employee_id", sa.text("submitted_at DESC")],
    )
    op.create_index(
        "ix_assignment_status",
        "employee_salary_structure_assignment", ["status"],
    )

    # ---------- employee_salary_structure_assignment_attempt ----------
    op.create_table(
        "employee_salary_structure_assignment_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_salary_structure_assignment.id",
                          ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "attempted_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attempted_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("failure_detail", sa.Text, nullable=True),
        sa.CheckConstraint(
            "outcome IN ('approved','failed','rejected','cancelled')",
            name="ck_assignment_attempt_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'failed' AND failure_detail IS NOT NULL) "
            "OR (outcome <> 'failed' AND failure_detail IS NULL)",
            name="ck_assignment_attempt_failure_detail",
        ),
    )
    op.create_index(
        "ix_assignment_attempt_history",
        "employee_salary_structure_assignment_attempt",
        ["assignment_id", sa.text("attempted_at DESC")],
    )

    # ---------- additive columns on existing tables ----------
    op.add_column(
        "employee_earning",
        sa.Column("source_assignment_id",
                  postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_employee_earning_source_assignment",
        "employee_earning", "employee_salary_structure_assignment",
        ["source_assignment_id"], ["id"], ondelete="RESTRICT",
    )

    op.add_column(
        "employee_deduction",
        sa.Column("source_assignment_id",
                  postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_employee_deduction_source_assignment",
        "employee_deduction", "employee_salary_structure_assignment",
        ["source_assignment_id"], ["id"], ondelete="RESTRICT",
    )

    op.add_column(
        "employee_pay_history",
        sa.Column("source_assignment_id",
                  postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_employee_pay_history_source_assignment",
        "employee_pay_history", "employee_salary_structure_assignment",
        ["source_assignment_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_employee_pay_history_employee_approved_rate",
        "employee_pay_history",
        ["employee_id", sa.text("effective_from DESC")],
        postgresql_where=sa.text("status = 'approved'"),
    )

    op.add_column(
        "payroll_change_request",
        sa.Column("assignment_id",
                  postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_payroll_change_request_assignment",
        "payroll_change_request", "employee_salary_structure_assignment",
        ["assignment_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_payroll_change_request_assignment",
        "payroll_change_request", type_="foreignkey",
    )
    op.drop_column("payroll_change_request", "assignment_id")

    op.drop_index(
        "ix_employee_pay_history_employee_approved_rate",
        table_name="employee_pay_history",
    )
    op.drop_constraint(
        "fk_employee_pay_history_source_assignment",
        "employee_pay_history", type_="foreignkey",
    )
    op.drop_column("employee_pay_history", "source_assignment_id")

    op.drop_constraint(
        "fk_employee_deduction_source_assignment",
        "employee_deduction", type_="foreignkey",
    )
    op.drop_column("employee_deduction", "source_assignment_id")

    op.drop_constraint(
        "fk_employee_earning_source_assignment",
        "employee_earning", type_="foreignkey",
    )
    op.drop_column("employee_earning", "source_assignment_id")

    op.drop_index(
        "ix_assignment_attempt_history",
        table_name="employee_salary_structure_assignment_attempt",
    )
    op.drop_table("employee_salary_structure_assignment_attempt")

    op.drop_index("ix_assignment_status",
                  table_name="employee_salary_structure_assignment")
    op.drop_index("ix_assignment_employee_submitted",
                  table_name="employee_salary_structure_assignment")
    op.drop_index("uq_assignment_idempotency",
                  table_name="employee_salary_structure_assignment")
    op.drop_index("uq_open_approved_assignment",
                  table_name="employee_salary_structure_assignment")
    op.drop_index("uq_pending_assignment_per_employee",
                  table_name="employee_salary_structure_assignment")
    op.drop_table("employee_salary_structure_assignment")

    op.drop_table("salary_structure_component")

    op.drop_index("uq_salary_structure_current",
                  table_name="salary_structure")
    op.drop_table("salary_structure")

# END OF FILE