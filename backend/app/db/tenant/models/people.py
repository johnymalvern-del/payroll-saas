"""Tenant ORM models: employees, users, scopes, biometric consent.

Columns that hold encrypted content (national_id_encrypted,
bank_account_number_encrypted, mfa_secret_encrypted) are plain Text at the
database level. The application encrypts before writing and decrypts after
reading, using TenantCrypto. This is deliberate: a ContextVar-held key is
not visible across FastAPI thread boundaries, so the key must be passed as
a value, not carried implicitly.

Columns added by migration 0008:
  * Employee.row_version - optimistic-concurrency guard for PATCH
    /api/v1/employees/{id}. row_version was already present on Company,
    Branch, Site and Department (see migration 0004); 1C.8 adds it here so
    employee PATCH follows the same contract as the other organisation
    endpoints.
"""
from __future__ import annotations

import uuid  # noqa: F401 - required because Mapped[uuid.UUID] annotations resolve at runtime
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk


class Employee(Base, TimestampMixin):
    __tablename__ = "employee"
    __table_args__ = (UniqueConstraint("employee_code", name="uq_employee_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    national_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    mobile: Mapped[str | None] = mapped_column(String(40), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branch.id", ondelete="SET NULL"), nullable=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("department.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id", ondelete="SET NULL"), nullable=True
    )
    employee_type: Mapped[str] = mapped_column(String(20), nullable=False, default="hourly")
    pay_basis: Mapped[str] = mapped_column(String(20), nullable=False, default="hourly")
    pay_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    base_rate: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    overtime_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    clocks: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    work_pattern_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    default_shift_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_account_number_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_branch_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tax_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    medical_aid_dependants: Mapped[int] = mapped_column(nullable=False, default=0)
    retirement_fund_flags: Mapped[str | None] = mapped_column(String(120), nullable=True)
    uif_exempt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contracted_weekly_hours: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    medical_scheme_members: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class EmployeePayHistory(Base, TimestampMixin):
    __tablename__ = "employee_pay_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    base_rate: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")


class User(Base, TimestampMixin):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("username", name="uq_user_username"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="employee")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class UserScope(Base, TimestampMixin):
    __tablename__ = "user_scope"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)


class BiometricConsent(Base, TimestampMixin):
    __tablename__ = "biometric_consent"

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    consent_text_version: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    captured_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    method: Mapped[str] = mapped_column(String(40), nullable=False, default="digital")


class BiometricEnrolment(Base, TimestampMixin):
    __tablename__ = "biometric_enrolment"

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    template_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    vendor: Mapped[str] = mapped_column(String(60), nullable=False)
    template_version: Mapped[str] = mapped_column(String(40), nullable=False)
    consent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("biometric_consent.id", ondelete="RESTRICT"),
        nullable=False,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

# END OF FILE
# _4A_BIS_011 people
