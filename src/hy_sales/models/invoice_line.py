"""``sales.invoice_lines`` — invoice line items."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class InvoiceLine(Base):
    """One row per product line on an invoice.

    Re-uploading an invoice deletes-and-reinserts all its lines, so
    there's only ``created_at`` (no ``updated_at``). Commission columns
    are intentionally absent — flat 10% derived at query time from
    ``sales.app_config('commission_rate')``.
    """

    __tablename__ = "invoice_lines"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="chk_invoice_lines_quantity"),
        CheckConstraint("amount >= 0", name="chk_invoice_lines_amount"),
        UniqueConstraint(
            "invoice_id",
            "line_seq",
            name="uq_invoice_lines_invoice_seq",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    invoice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales.invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_seq: Mapped[int] = mapped_column(Integer, nullable=False)

    product_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sales.products.id"),
        nullable=True,
    )
    product_raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    sales_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    file_upload_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales.file_uploads.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
