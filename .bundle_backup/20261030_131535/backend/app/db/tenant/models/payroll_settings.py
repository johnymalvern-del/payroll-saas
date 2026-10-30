"""Payroll settings (Chapter 4, Bundle 003b).

Singleton row per tenant. Controls E4 (sdl_applies), E6 (age_reference_date),
D14 (net_pay_floor). GET returns defaults when no row exists; PATCH creates
or updates the row. row_version guards concurrent edits.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PayrollSettings(Base):
    __tablename__ = "payroll_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    age_reference_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sdl_applies: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    net_pay_floor: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

# END OF FILE
