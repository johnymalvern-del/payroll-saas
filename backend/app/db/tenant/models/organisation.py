from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class Company(Base, TimestampMixin):
    """Single-row table per tenant database."""

    __tablename__ = "company"

    id: Mapped[uuid.UUID] = uuid_pk()
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tax_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    paye_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    uif_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sdl_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    coida_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="ZA")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ZAR")
    default_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Africa/Johannesburg"
    )
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Branch(Base, TimestampMixin):
    __tablename__ = "branch"
    __table_args__ = (UniqueConstraint("code", name="uq_branch_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)


class Site(Base, TimestampMixin):
    __tablename__ = "site"
    __table_args__ = (UniqueConstraint("code", name="uq_site_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branch.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    site_type: Mapped[str] = mapped_column(String(20), nullable=False, default="site")
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Africa/Johannesburg"
    )
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    geofence_radius_m: Mapped[int | None] = mapped_column(nullable=True)

    branch: Mapped[Branch] = relationship(Branch, lazy="joined")


class Department(Base, TimestampMixin):
    __tablename__ = "department"
    __table_args__ = (UniqueConstraint("code", name="uq_department_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("department.id", ondelete="SET NULL"),
        nullable=True,
    )