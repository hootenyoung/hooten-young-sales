"""``field.rep_profiles`` — per-rep profile data.

One row per user with the field_rep role.  Carries home address (used
later for distance-from-home routing) and phone.  Lives in its own
table — not as columns on auth.users — because most users are not
reps; we don't want every users row carrying nullable rep-only fields.

The user_id is BOTH the PK and the FK to auth.users — a user is
either a rep or not, never two profiles.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class FieldRepProfile(Base):
    __tablename__ = "rep_profiles"
    __table_args__ = ({"schema": "field"},)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    home_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    home_city: Mapped[str | None] = mapped_column(Text, nullable=True)
    home_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    home_zip: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)

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
