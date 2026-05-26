"""``sales.customers`` — QuickBooks Customer entities (bill-to)."""

from __future__ import annotations

from sqlalchemy import CHAR, BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class Customer(Base, DimMixin):
    """The entities HY directly invoices.

    One distributor typically has many customer rows (e.g. RNDC's
    Houston operation, RNDC's Schertz operation). ``state_code`` is
    nullable for ambiguous customer names that need source-side cleanup.
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    canonical_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    distributor_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sales.distributors.id"),
        nullable=True,
    )
    state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    territory: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
