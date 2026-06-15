"""``depletions.file_uploads`` — audit ledger for ingested depletions files.

Separate from ``sales.file_uploads`` so the two feeds' upload histories
are physically isolated. No ``kind`` discriminator column — every row in
this table is a depletions upload by definition.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class DepFileUpload(Base):
    __tablename__ = "file_uploads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'success', 'failed', 'partial')",
            name="chk_dep_file_uploads_status",
        ),
        {"schema": "depletions"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    uploaded_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="pending",
    )
    row_count_processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    row_count_inserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    row_count_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    row_count_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    row_count_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
