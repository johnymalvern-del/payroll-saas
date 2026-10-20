from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk


class Subscriber(Base, TimestampMixin):
    __tablename__ = "subscriber"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="ZA")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="provisioning")
    provisioning_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    provisioning_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tenant_db_name: Mapped[str | None] = mapped_column(String(63), nullable=True)
    tenant_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encryption_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)


class PlatformUser(Base, TimestampMixin):
    __tablename__ = "platform_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="platform_admin")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CountryProfile(Base, TimestampMixin):
    __tablename__ = "country_profile"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_country_profile_code_version"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class PublicHoliday(Base, TimestampMixin):
    __tablename__ = "public_holiday"
    __table_args__ = (
        UniqueConstraint(
            "country_code", "holiday_date", "name", name="uq_public_holiday_identity"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)


class StatutoryTable(Base, TimestampMixin):
    __tablename__ = "statutory_table"
    __table_args__ = (
        UniqueConstraint(
            "country_code",
            "table_key",
            "tax_year",
            "version",
            name="uq_statutory_table_identity",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    table_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ControlAuditLog(Base):
    __tablename__ = "control_audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)