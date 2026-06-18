"""``field.rep_territories`` — many-to-many (rep, state).

A rep can cover multiple states; a state is normally covered by
exactly one rep but the schema doesn't enforce uniqueness — overlap
is allowed during transitions and surfaced to admins.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class FieldRepTerritory(Base):
    __tablename__ = "rep_territories"
    __table_args__ = ({"schema": "field"},)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    state_code: Mapped[str] = mapped_column(String(2), primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
