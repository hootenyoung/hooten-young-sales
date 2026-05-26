"""``sales.customer_aliases`` — raw text → canonical customer."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class CustomerAlias(Base, DimMixin):
    """Maps raw QuickBooks Customer strings to canonical customers.

    Different broker formats spell the same customer differently; this
    table decouples raw spellings from the canonical entity.
    """

    __tablename__ = "customer_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    alias_text: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales.customers.id"),
        nullable=False,
    )
    source_system: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="quickbooks",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
