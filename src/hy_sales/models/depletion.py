"""``sales.depletions`` — long-format depletion facts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, TimestampMixin


class Depletion(Base, TimestampMixin):
    """One row per (account, product, month) — long format.

    ``cases_9l`` (9-Liter Equivalents) is always present;
    ``cases_physical`` is nullable to accommodate older broker formats
    that don't include it.

    Note on column name: in SQL the column is declared ``cases_9L`` but
    Postgres folds unquoted identifiers to lowercase, so the actual
    column is ``cases_9l``. The Python attribute matches the actual
    column name.
    """

    __tablename__ = "depletions"
    __table_args__ = (
        CheckConstraint(
            "EXTRACT(DAY FROM period_month) = 1",
            name="chk_depletions_period_first_of_month",
        ),
        # Note: cases_9l / cases_physical CAN be negative — they represent
        # product returns from retail back to the distributor (pullbacks).
        # The non-negative CHECK constraints originally on these columns
        # were dropped in db/migrations/002_depletions_allow_negatives.sql.
        UniqueConstraint(
            "account_id",
            "product_id",
            "period_month",
            name="uq_depletions_natural",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales.accounts.id"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales.products.id"),
        nullable=False,
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)

    cases_9l: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    cases_physical: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)

    file_upload_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales.file_uploads.id"),
        nullable=False,
    )
