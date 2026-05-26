"""``sales.products`` — canonical SKU catalog."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class Product(Base, DimMixin):
    """Canonical Hooten Young products.

    One row per real SKU. Raw strings from source files resolve to
    a product via ``product_aliases``.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    full_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    pack_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bottle_size_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
