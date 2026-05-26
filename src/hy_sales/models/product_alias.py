"""``sales.product_aliases`` — raw text → canonical product."""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class ProductAlias(Base, DimMixin):
    """Maps raw product strings from source files to canonical products.

    Sales feed uses ALL-CAPS truncated names; depletions feed uses
    differently truncated names. Both resolve here to one canonical row.
    """

    __tablename__ = "product_aliases"
    __table_args__ = (
        CheckConstraint(
            "source IN ('sales', 'depletions', 'manual')",
            name="chk_product_aliases_source",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    alias_text: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales.products.id"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
