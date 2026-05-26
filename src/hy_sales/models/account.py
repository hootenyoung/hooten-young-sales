"""``sales.accounts`` — retail locations from the depletions feed."""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class Account(Base, DimMixin):
    """Retail accounts — liquor stores, bars, restaurants.

    Natural key is ``(name, address, state_code)`` — same chain at
    different addresses are different rows. ``premises_type`` captures
    on-premise (bars/restaurants) vs off-premise (retail) when known.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "premises_type IS NULL OR premises_type IN ('ON', 'OFF')",
            name="chk_accounts_premises",
        ),
        UniqueConstraint(
            "name",
            "address",
            "state_code",
            name="uq_accounts_natural",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    distributor_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sales.distributors.id"),
        nullable=True,
    )
    distributor_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    premises_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
