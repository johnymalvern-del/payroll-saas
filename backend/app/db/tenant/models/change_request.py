"""Payroll change requests (Chapter 4, Bundle 004a-iv-a).

F3 mechanism: HR submits, payroll_admin approves. Approver must differ from
requester. Pending requests have zero effect on employee_earning,
employee_deduction, or employee fields until approved. Approved requests
write through to the target table within the same transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


KINDS = (
    "employee_earning_create",
    "employee_earning_update",
    "employee_earning_deactivate",
    "employee_deduction_create",
    "employee_deduction_update",
    "employee_deduction_deactivate",
    "employee_field_update",
)

STATUSES = ("pending", "approved", "rejected", "cancelled")


class PayrollChangeRequest(Base):
    __tablename__ = "payroll_change_request"
    __table_args__ = (
        CheckConstraint(
            "kind IN (" + ",".join(f"'{k}'" for k in KINDS) + ")",
            name="ck_payroll_change_request_kind",
        ),
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in STATUSES) + ")",
            name="ck_payroll_change_request_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
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
    applied_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

# END OF FILE
