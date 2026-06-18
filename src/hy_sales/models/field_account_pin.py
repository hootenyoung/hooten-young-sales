"""``field.account_pins`` — rep-flagged "visit this next" entries.

Composite PK (rep_id, account_id) so each rep keeps their own pin
list — two reps both covering the same account each pin independently.

Pins get a strong priority-score boost; the rep clears them by
unpinning via the UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class FieldAccountPin(Base):
    __tablename__ = "account_pins"
    __table_args__ = ({"schema": "field"},)

    rep_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("depletions.accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
