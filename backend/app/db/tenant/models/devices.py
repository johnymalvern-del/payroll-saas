from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk


class Device(Base, TimestampMixin):
    __tablename__ = "device"
    __table_args__ = (
        UniqueConstraint("api_key_hash", name="uq_device_api_key_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    device_type: Mapped[str] = mapped_column(String(30), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="offline")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_punch_count: Mapped[int] = mapped_column(nullable=False, default=0)
    allows_code_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_photo_for_code: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    software_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    row_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

# END OF FILE
    row_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

# END OF FILE