"""``sales.distributors`` — 3-tier middle-layer entities."""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class Distributor(Base, DimMixin):
    """Parent distributor entities — RNDC, Empire, etc., plus state control
    boards and military exchanges (the latter two classified via
    ``channel``)."""

    __tablename__ = "distributors"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('distributor', 'control_state', 'military', 'other')",
            name="chk_distributors_channel",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default="distributor")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
