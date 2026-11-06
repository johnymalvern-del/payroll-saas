"""Intelligence foundation (Phase 1A).

Creates 5 tables. No existing table is altered. No column is dropped.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ten_0025"
down_revision = "ten_0024"
branch_labels = None
depends_on = None

_MODES = "('traditional', 'assisted', 'autonomous')"
_WORKFLOWS = (
    "('leave_decision', 'attendance_correction', 'payslip_complaint', "
    "'overtime_classification', 'payroll_adjustment', "
    "'statutory_compliance_exception')"
)


def upgrade() -> None:
    op.create_table(
        "intelligence_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "default_mode", sa.String(20), nullable=False,
            server_default=sa.text("'traditional'"),
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acknowledged_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("row_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"default_mode IN {_MODES}",
            name="ck_intelligence_settings_default_mode",
        ),
    )

    op.create_table(
        "intelligence_workflow_mode",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("effective_from", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("row_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workflow",
                            name="uq_intelligence_workflow_mode_workflow"),
        sa.CheckConstraint(f"workflow IN {_WORKFLOWS}",
                           name="ck_intelligence_workflow_mode_workflow"),
        sa.CheckConstraint(f"mode IN {_MODES}",
                           name="ck_intelligence_workflow_mode_mode"),
    )

    op.create_table(
        "intelligence_mode_change_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "changed_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("workflow", sa.String(40), nullable=True),
        sa.Column("previous_mode", sa.String(20), nullable=False),
        sa.Column("new_mode", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "audit_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audit_log.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.CheckConstraint(
            f"workflow IS NULL OR workflow IN {_WORKFLOWS}",
            name="ck_intelligence_mode_change_log_workflow",
        ),
        sa.CheckConstraint(f"previous_mode IN {_MODES}",
                           name="ck_intelligence_mode_change_log_prev"),
        sa.CheckConstraint(f"new_mode IN {_MODES}",
                           name="ck_intelligence_mode_change_log_new"),
    )

    op.create_table(
        "intelligence_decision",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("workflow", sa.String(40), nullable=False, index=True),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_snapshot", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("policy_version", sa.String(40), nullable=True),
        sa.Column("statutory_version", sa.String(40), nullable=True),
        sa.Column("mode_at_creation", sa.String(20), nullable=False),
        sa.Column("recommendation", postgresql.JSONB, nullable=True),
        sa.Column("explanation", sa.Text, nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("rule_completeness", sa.Numeric(5, 4), nullable=True),
        sa.Column("human_decision", sa.String(20), nullable=True),
        sa.Column(
            "human_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("human_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agreement", sa.Boolean, nullable=True),
        sa.Column("final_action", sa.String(40), nullable=True),
        sa.Column("execution_status", sa.String(20), nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_error", sa.Text, nullable=True),
        sa.Column(
            "audit_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audit_log.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"workflow IN {_WORKFLOWS}",
                           name="ck_intelligence_decision_workflow"),
        sa.CheckConstraint(f"mode_at_creation IN {_MODES}",
                           name="ck_intelligence_decision_mode"),
    )
    op.create_index(
        "ix_intelligence_decision_workflow_status",
        "intelligence_decision", ["workflow", "execution_status"],
    )

    op.create_table(
        "intelligence_decision_override_reason",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "decision_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intelligence_decision.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("reason_code", sa.String(40), nullable=False),
        sa.Column("reason_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("intelligence_decision_override_reason")
    op.drop_index("ix_intelligence_decision_workflow_status",
                  table_name="intelligence_decision")
    op.drop_table("intelligence_decision")
    op.drop_table("intelligence_mode_change_log")
    op.drop_table("intelligence_workflow_mode")
    op.drop_table("intelligence_settings")
