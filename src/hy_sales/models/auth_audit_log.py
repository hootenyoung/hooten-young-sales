"""``auth.audit_log`` — append-only record of meaningful auth events.

Used for forensics, abuse review, and admin transparency ("who did
what, when"). Never UPDATE or DELETE rows in this table.

``user_id`` is nullable on purpose: failed-login attempts against
unknown emails still get recorded for abuse detection, with the
metadata column carrying the attempted email.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class AuthAuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = ({"schema": "auth"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id"),
        nullable=True,
    )

    # Free-form action key. See migration 003 for the known values.
    action: Mapped[str] = mapped_column(Text, nullable=False)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
