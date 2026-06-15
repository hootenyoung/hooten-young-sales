"""``depletions.products`` — canonical product catalog for the depletions feed."""

from __future__ import annotations

from sqlalchemy import BigInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class DepProduct(Base, DimMixin):
    """One row per SKU as the depletions feed labels it.

    Physically distinct from ``sales.products`` so the two feeds'
    differently-spelled names cannot collide on the same alias and
    misroute. Cross-feed reconciliation (when needed) belongs in a
    dedicated mapping table, not here.
    """

    __tablename__ = "products"
    __table_args__ = ({"schema": "depletions"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    full_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
