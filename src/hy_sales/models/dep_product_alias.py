"""``depletions.product_aliases`` — raw depletions strings → canonical product."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class DepProductAlias(Base, DimMixin):
    """Verbatim raw string from a depletions source file → ``DepProduct``.

    The iDIG export truncates product names to ~25 chars; future
    depletion sources will spell them differently. Aliases absorb that
    without requiring parser-side string manipulation.
    """

    __tablename__ = "product_aliases"
    __table_args__ = ({"schema": "depletions"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    alias_text: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("depletions.products.id"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
