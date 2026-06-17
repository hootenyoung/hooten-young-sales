"""``platform.app_config`` — cross-domain key/value store.

A single table that holds runtime settings any subsystem may need —
feedback recipients today; could be feature flags, default values,
campaign windows, etc. tomorrow.

See ``db/migrations/007_auth_feedback.sql`` for the SQL definition and
the key-naming convention.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class PlatformAppConfig(Base):
    __tablename__ = "app_config"
    __table_args__ = ({"schema": "platform"},)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
