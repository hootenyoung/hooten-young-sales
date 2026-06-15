"""``depletions.accounts`` — retail accounts from the depletions feed.

Natural key is ``(name, address, state_code)``; ``state_code`` is the
account's physical state. ``dist_state_code`` is the servicing
distributor's state, which can differ. ``distributor_code`` is the raw
short code from iDIG (e.g. ``"FL13"``) — no FK to a canonical
distributor entity because the depletions feed doesn't carry full
distributor names.
"""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class DepAccount(Base, DimMixin):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "premises_type IS NULL OR premises_type IN ('ON', 'OFF', 'NA')",
            name="chk_dep_accounts_premises",
        ),
        UniqueConstraint(
            "name",
            "address",
            "state_code",
            name="uq_dep_accounts_natural",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "depletions"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    county: Mapped[str | None] = mapped_column(Text, nullable=True)
    zip_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    dist_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    distributor_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    premises_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
