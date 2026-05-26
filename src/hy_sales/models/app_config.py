"""``sales.app_config`` — runtime-tunable business parameters."""

from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from hy_sales.models.base import Base, DimMixin


class AppConfig(Base, DimMixin):
    """Key-value config for runtime-tunable business values.

    Holds things like ``commission_rate`` and
    ``current_sales_source_system``. To change a value: UPDATE the row
    in the live database — no redeploy required. See CLAUDE.md for the
    pattern.
    """

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
