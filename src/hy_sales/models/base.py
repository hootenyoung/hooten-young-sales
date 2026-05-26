"""SQLAlchemy ORM base class and shared column mixins.

All models live under the ``sales`` Postgres schema, configured at the
``MetaData`` level so individual models don't have to repeat the schema
name.

The SQL migration in ``db/migrations/001_sales_schema.sql`` is the
source of truth for table structure. These ORM models exist purely for
query ergonomics — we never call ``Base.metadata.create_all()``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for every hy_sales ORM model.

    Sets the default schema to ``sales``. Subclasses can still add their
    own ``__table_args__`` tuple (constraints, indexes) — the schema
    binding survives because it lives on ``metadata``, not in
    ``__table_args__``.
    """

    metadata = MetaData(schema="sales")


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns.

    Both default to ``now()`` on INSERT. ``updated_at`` is bumped on
    every UPDATE via SQLAlchemy's ``onupdate`` hook — no DB trigger.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftActiveMixin:
    """Adds an ``is_active`` boolean defaulting to true.

    Used on dimension / config tables to soft-disable rows without
    losing history. Fact tables (invoices, invoice_lines, depletions)
    don't use this — they have ``file_upload_id`` for audit instead.
    """

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False,
    )


class DimMixin(TimestampMixin, SoftActiveMixin):
    """Combines ``created_at``, ``updated_at``, and ``is_active``.

    Apply to dimension and config tables: app_config, products,
    product_aliases, distributors, customers, customer_aliases, accounts.
    """
