"""``depletions.facts`` — long-format depletion facts.

One row per (account, product, month). ``cases_9l`` is always present;
``cases_physical`` is nullable because the iDIG Rolling Periods export
carries 9-Liter Equivs only. Both columns may be negative (pullbacks /
retail returns).
"""

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


class DepFact(Base, TimestampMixin):
    __tablename__ = "facts"
    __table_args__ = (
        CheckConstraint(
            "EXTRACT(DAY FROM period_month) = 1",
            name="chk_dep_facts_period_first_of_month",
        ),
        UniqueConstraint(
            "account_id",
            "product_id",
            "period_month",
            name="uq_dep_facts_natural",
        ),
        {"schema": "depletions"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("depletions.accounts.id"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("depletions.products.id"),
        nullable=False,
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)

    cases_9l: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    cases_physical: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)

    file_upload_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("depletions.file_uploads.id"),
        nullable=False,
    )
