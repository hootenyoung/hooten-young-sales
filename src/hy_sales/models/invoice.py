"""``sales.invoices`` — invoice headers."""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, TimestampMixin


class Invoice(Base, TimestampMixin):
    """One row per source-system invoice (e.g. QuickBooks ``Num`` like
    ``SI-012682``).

    Composite unique on ``(source_system, invoice_ref)`` so old and new
    broker formats can coexist without invoice-number collisions.
    ``customer_id`` is nullable when the alias isn't yet resolved;
    ``customer_raw_text`` always preserves the verbatim source string.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('invoice', 'credit_memo', 'other')",
            name="chk_invoices_transaction_type",
        ),
        UniqueConstraint(
            "source_system",
            "invoice_ref",
            name="uq_invoices_source_ref",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_ref: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="invoice",
    )

    customer_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sales.customers.id"),
        nullable=True,
    )
    customer_raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    po_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    file_upload_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales.file_uploads.id"),
        nullable=False,
    )
