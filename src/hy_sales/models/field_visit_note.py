"""``field.visit_notes`` — the CRM activity log.

One row per visit or call by a rep against an account.  Drives:

  * "last visit" math used in the priority score
  * Cooldowns — outcome determines days until the account can
    resurface in Today's list (see services/field_priority.py)
  * Admin oversight — cross-rep recent-activity feed
  * Per-account history — chronological notes timeline in the UI

Channel + outcome are constrained at the DB layer; schemas package
mirrors them as Literal types.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class FieldVisitNote(Base):
    __tablename__ = "visit_notes"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('visit', 'call')",
            name="visit_notes_channel_chk",
        ),
        CheckConstraint(
            "outcome IN ('ordered', 'follow_up_needed', 'no_response', 'declined', 'info_only')",
            name="visit_notes_outcome_chk",
        ),
        {"schema": "field"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("depletions.accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    rep_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )

    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
