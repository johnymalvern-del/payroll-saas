"""Salary structure ORM models (Chapter 4, Milestone 3, Bundle ten_0027).

Four tables:
  * salary_structure                             - one row per version
  * salary_structure_component                   - component rows per version
  * employee_salary_structure_assignment         - submit/approve/reject/cancel
  * employee_salary_structure_assignment_attempt - append-only attempt history

Following the precedent set in pay.py, these models are NOT re-exported via
app.db.tenant.models.__init__; the schema-drift test discovers tables via
Base.metadata and the drift-test surface stays stable across the M3 rollout.
Endpoints and services import these classes directly.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SalaryStructure(Base):
    __tablename__ = "salary_structure"
    __table_args__ = (
        UniqueConstraint(
            "structure_group_id", "version_number",
            name="uq_salary_structure_group_version",
        ),
        Index(
            "uq_salary_structure_current",
            "structure_group_id",
            unique=True,
            postgresql_where=text("is_current = TRUE"),
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_salary_structure_version_positive",
        ),
        CheckConstraint(
            "pay_basis IN ('hourly','daily','monthly')",
            name="ck_salary_structure_pay_basis",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    structure_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    pay_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    base_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE"),
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )


class SalaryStructureComponent(Base):
    __tablename__ = "salary_structure_component"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('earning','deduction')",
            name="ck_salary_structure_component_kind",
        ),
        CheckConstraint(
            "(kind = 'earning' AND earning_type_id IS NOT NULL AND deduction_type_id IS NULL) "
            "OR (kind = 'deduction' AND deduction_type_id IS NOT NULL AND earning_type_id IS NULL)",
            name="ck_salary_structure_component_type_exclusive",
        ),
        CheckConstraint(
            "(kind = 'deduction' AND amount IS NOT NULL AND rate IS NULL) "
            "OR (kind = 'earning' AND ((amount IS NULL) <> (rate IS NULL)))",
            name="ck_salary_structure_component_amount_or_rate",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    structure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("salary_structure.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    earning_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("earning_type.id", ondelete="RESTRICT"),
        nullable=True,
    )
    deduction_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deduction_type.id", ondelete="RESTRICT"),
        nullable=True,
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class EmployeeSalaryStructureAssignment(Base):
    __tablename__ = "employee_salary_structure_assignment"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled')",
            name="ck_assignment_status",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_assignment_effective_range",
        ),
        Index(
            "uq_pending_assignment_per_employee",
            "employee_id", unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "uq_open_approved_assignment",
            "employee_id", unique=True,
            postgresql_where=text("status = 'approved' AND effective_to IS NULL"),
        ),
        Index(
            "uq_assignment_idempotency",
            "idempotency_key", unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_assignment_employee_submitted",
            "employee_id", text("submitted_at DESC"),
        ),
        Index("ix_assignment_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    structure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("salary_structure.id", ondelete="RESTRICT"),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        server_default=text("'pending'"),
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_manual_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        server_default=text("'[]'::jsonb"),
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )


class EmployeeSalaryStructureAssignmentAttempt(Base):
    __tablename__ = "employee_salary_structure_assignment_attempt"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('approved','failed','rejected','cancelled')",
            name="ck_assignment_attempt_outcome",
        ),
        CheckConstraint(
            "(outcome = 'failed' AND failure_detail IS NOT NULL) "
            "OR (outcome <> 'failed' AND failure_detail IS NULL)",
            name="ck_assignment_attempt_failure_detail",
        ),
        Index(
            "ix_assignment_attempt_history",
            "assignment_id", text("attempted_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee_salary_structure_assignment.id",
                   ondelete="RESTRICT"),
        nullable=False,
    )
    attempted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

# END OF FILE