"""Phase 1A — migration 0025 + intelligence models."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"

# ---------- 1. Migration ----------
mig = BE / "alembic" / "tenant" / "versions" / "0025_intelligence_foundation.py"
mig.write_text('''"""Intelligence foundation (Phase 1A).

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
''', encoding="utf-8")
print("wrote backend/alembic/tenant/versions/0025_intelligence_foundation.py")

# ---------- 2. Models ----------
models = BE / "app" / "db" / "tenant" / "models" / "intelligence.py"
models.write_text('''"""Intelligence foundation models (Phase 1A).

Not imported by app.db.tenant.models.__init__ — same pattern as pay.py.
The service and API router import these classes directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


MODES: tuple[str, ...] = ("traditional", "assisted", "autonomous")
WORKFLOWS: tuple[str, ...] = (
    "leave_decision",
    "attendance_correction",
    "payslip_complaint",
    "overtime_classification",
    "payroll_adjustment",
    "statutory_compliance_exception",
)

_MODES_IN = "('traditional', 'assisted', 'autonomous')"
_WORKFLOWS_IN = (
    "('leave_decision', 'attendance_correction', 'payslip_complaint', "
    "'overtime_classification', 'payroll_adjustment', "
    "'statutory_compliance_exception')"
)


def _pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class IntelligenceSettings(Base):
    __tablename__ = "intelligence_settings"
    __table_args__ = (
        CheckConstraint(f"default_mode IN {_MODES_IN}",
                        name="ck_intelligence_settings_default_mode"),
    )

    id: Mapped[uuid.UUID] = _pk()
    default_mode: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default="traditional", server_default=text("'traditional'"),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )


class IntelligenceWorkflowMode(Base):
    __tablename__ = "intelligence_workflow_mode"
    __table_args__ = (
        UniqueConstraint("workflow", name="uq_intelligence_workflow_mode_workflow"),
        CheckConstraint(f"workflow IN {_WORKFLOWS_IN}",
                        name="ck_intelligence_workflow_mode_workflow"),
        CheckConstraint(f"mode IN {_MODES_IN}",
                        name="ck_intelligence_workflow_mode_mode"),
    )

    id: Mapped[uuid.UUID] = _pk()
    workflow: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )


class IntelligenceModeChangeLog(Base):
    __tablename__ = "intelligence_mode_change_log"
    __table_args__ = (
        CheckConstraint(
            f"workflow IS NULL OR workflow IN {_WORKFLOWS_IN}",
            name="ck_intelligence_mode_change_log_workflow",
        ),
        CheckConstraint(f"previous_mode IN {_MODES_IN}",
                        name="ck_intelligence_mode_change_log_prev"),
        CheckConstraint(f"new_mode IN {_MODES_IN}",
                        name="ck_intelligence_mode_change_log_new"),
    )

    id: Mapped[uuid.UUID] = _pk()
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    workflow: Mapped[str | None] = mapped_column(String(40), nullable=True)
    previous_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    new_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    audit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_log.id", ondelete="SET NULL"),
        nullable=True,
    )


class IntelligenceDecision(Base):
    __tablename__ = "intelligence_decision"
    __table_args__ = (
        CheckConstraint(f"workflow IN {_WORKFLOWS_IN}",
                        name="ck_intelligence_decision_workflow"),
        CheckConstraint(f"mode_at_creation IN {_MODES_IN}",
                        name="ck_intelligence_decision_mode"),
    )

    id: Mapped[uuid.UUID] = _pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    workflow: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    evidence_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    policy_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    statutory_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mode_at_creation: Mapped[str] = mapped_column(String(20), nullable=False)
    recommendation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    rule_completeness: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    human_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    human_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    human_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    agreement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    final_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    execution_status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default="pending", server_default=text("'pending'"),
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_log.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IntelligenceDecisionOverrideReason(Base):
    __tablename__ = "intelligence_decision_override_reason"

    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("intelligence_decision.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
''', encoding="utf-8")
print("wrote backend/app/db/tenant/models/intelligence.py")

print("\nP1A stage 1 complete.")