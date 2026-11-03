"""Payroll settings (Chapter 4 Bundle 003b + Chapter 4H B-4 + Chapter 3 L1a).

Chapter 4H adds the attendance-to-earnings settings. Chapter 3 L1a adds
leave approval chain extras, chapter 3 accountant-gated settings, and
sick-leave code list. Every money/law-affecting field is NULLABLE with
no invented default; the run must 409 unless the tenant sets it.

`demo_values` marks tenants seeded by demo_seed; payslip PDFs for those
tenants carry a "DEMO - NOT A REAL PAYSLIP" mark.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PayrollSettings(Base):
    __tablename__ = "payroll_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    age_reference_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sdl_applies: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    net_pay_floor: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    formula_acks: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Chapter 4H — attendance-to-earnings integration settings.
    attendance_earning_map: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    unpaid_day_behaviour: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    unpaid_day_formula_code: Mapped[str | None] = mapped_column(
        String(60), nullable=True
    )
    public_holiday_unworked_monthly: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    public_holiday_paid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    leave_authoritative_source: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    monthly_hourly_derivation_formula_code: Mapped[str | None] = mapped_column(
        String(60), nullable=True
    )
    leave_earning_for_monthly: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )

    # Chapter 3 L1a — leave / advance / net-estimate settings (all nullable
    # with no invented default; unset = feature disabled, backend refuses).
    leave_escalation_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leave_cycle_fixed_anchor: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    advance_max_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    advance_hard_cap: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    sick_leave_codes: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    net_estimate_method: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Demo-tenant marker. Never set for real tenants.
    demo_values: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )