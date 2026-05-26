"""Read-side queries for the sales API.

Aggregates run in SQL against the ``sales.*`` tables. The API layer
(``hy_sales/api/sales.py``) is responsible for serialization; this
module just returns rows / dicts the routes can hand to Pydantic.

Why a separate module:
  Keeps SQL in one place per domain, separated from the FastAPI
  routing logic. Easier to reuse the same query from a CLI report
  later if needed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, distinct, func, select
from sqlalchemy.dialects.postgresql import array_agg
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import (
    AppConfig,
    Customer,
    Distributor,
    Invoice,
    InvoiceLine,
    Product,
)

DEFAULT_COMMISSION_RATE = Decimal("0.10")


async def get_commission_rate(session: AsyncSession) -> Decimal:
    """Read the current commission rate from ``sales.app_config``.

    Falls back to 10% if the row is missing/inactive — the historical
    flat rate. Logging a warning on fallback would be nice; deferred.
    """
    value = await session.scalar(
        select(AppConfig.value).where(
            AppConfig.key == "commission_rate",
            AppConfig.is_active.is_(True),
        )
    )
    if value is None:
        return DEFAULT_COMMISSION_RATE
    try:
        return Decimal(value)
    except (ValueError, ArithmeticError):
        return DEFAULT_COMMISSION_RATE


def _date_filter_clauses(date_from: date | None, date_to: date | None) -> list[Any]:
    clauses: list[Any] = []
    if date_from is not None:
        clauses.append(Invoice.invoice_date >= date_from)
    if date_to is not None:
        clauses.append(Invoice.invoice_date <= date_to)
    return clauses


async def get_sales_kpis(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Compute top-line KPIs for a date range."""
    clauses = _date_filter_clauses(date_from, date_to)

    # Aggregate over the invoice-line grain joined with the invoice header
    # (for date filtering) and optionally the customer (for state /
    # distributor counts).
    stmt = (
        select(
            func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"),
            func.coalesce(func.sum(InvoiceLine.quantity), 0).label("cases"),
            func.count(distinct(Invoice.id)).label("invoices"),
            func.count(distinct(InvoiceLine.product_id)).label("products"),
            func.count(distinct(Invoice.customer_id)).label("customers"),
            func.count(distinct(Customer.distributor_id)).label("distributors"),
            func.count(distinct(Customer.state_code)).label("states"),
            func.min(Invoice.invoice_date).label("period_start"),
            func.max(Invoice.invoice_date).label("period_end"),
        )
        .select_from(Invoice)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .join(Customer, Customer.id == Invoice.customer_id, isouter=True)
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    row = (await session.execute(stmt)).one()

    commission_rate = await get_commission_rate(session)
    revenue: Decimal = row.revenue
    invoices: int = row.invoices

    return {
        "total_revenue": revenue,
        "total_cases": row.cases,
        "total_commission": revenue * commission_rate,
        "commission_rate": commission_rate,
        "total_invoices": invoices,
        "avg_invoice_value": (revenue / invoices) if invoices > 0 else None,
        "unique_customers": row.customers,
        "unique_products": row.products,
        "unique_distributors": row.distributors,
        "unique_states": row.states,
        "period_start": row.period_start,
        "period_end": row.period_end,
    }


async def get_sales_trend(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    grain: str = "month",
) -> list[dict[str, Any]]:
    """Return time-bucketed sales aggregates ascending by period.

    ``grain`` accepts ``'month'`` or ``'week'`` — passed through to
    Postgres's ``date_trunc``. The week bucket aligns with ISO weeks.
    """
    clauses = _date_filter_clauses(date_from, date_to)
    bucket = func.date_trunc(grain, Invoice.invoice_date).cast(Date).label("period")

    stmt = (
        select(
            bucket,
            func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"),
            func.coalesce(func.sum(InvoiceLine.quantity), 0).label("cases"),
            func.count(distinct(Invoice.id)).label("invoices"),
        )
        .select_from(Invoice)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .group_by(bucket)
        .order_by(bucket)
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    return [
        {
            "period": row.period,
            "revenue": row.revenue,
            "cases": row.cases,
            "invoices": row.invoices,
        }
        for row in (await session.execute(stmt)).all()
    ]


# Keep the old name as an alias for backward compat.
get_sales_monthly_trend = get_sales_trend


async def get_sales_by_product(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return product-level aggregates sorted by revenue desc.

    Includes per-product distribution detail: state list, distributor list,
    and average price per case (revenue / cases).
    """
    clauses = _date_filter_clauses(date_from, date_to)

    stmt = (
        select(
            Product.id.label("product_id"),
            Product.full_name.label("product_name"),
            func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"),
            func.coalesce(func.sum(InvoiceLine.quantity), 0).label("cases"),
            func.count(distinct(InvoiceLine.invoice_id)).label("invoice_count"),
            array_agg(distinct(Customer.state_code))  # type: ignore[no-untyped-call]
            .filter(Customer.state_code.is_not(None))
            .label("states"),
            array_agg(distinct(Distributor.name))  # type: ignore[no-untyped-call]
            .filter(Distributor.name.is_not(None))
            .label("distributors"),
        )
        .select_from(InvoiceLine)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Product, Product.id == InvoiceLine.product_id)
        .join(Customer, Customer.id == Invoice.customer_id, isouter=True)
        .join(Distributor, Distributor.id == Customer.distributor_id, isouter=True)
        .group_by(Product.id, Product.full_name)
        .order_by(func.sum(InvoiceLine.amount).desc())
    )
    for clause in clauses:
        stmt = stmt.where(clause)
    if limit is not None:
        stmt = stmt.limit(limit)

    results: list[dict[str, Any]] = []
    for row in (await session.execute(stmt)).all():
        cases: Decimal = row.cases
        revenue: Decimal = row.revenue
        avg_price = (revenue / cases) if cases > 0 else None
        states: list[str] = sorted(row.states or [])
        distributors: list[str] = sorted(row.distributors or [])
        results.append(
            {
                "product_id": row.product_id,
                "product_name": row.product_name,
                "revenue": revenue,
                "cases": cases,
                "invoice_count": row.invoice_count,
                "avg_price_per_case": avg_price,
                "state_count": len(states),
                "states": states,
                "distributor_count": len(distributors),
                "distributors": distributors,
            }
        )
    return results


async def get_sales_by_state(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Return state-level aggregates sorted by revenue descending.

    State comes from ``customers.state_code``, populated by the
    customer-name parser. Invoices whose customer has a null
    state_code aggregate under ``state_code=None``.
    """
    clauses = _date_filter_clauses(date_from, date_to)

    stmt = (
        select(
            Customer.state_code.label("state_code"),
            func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"),
            func.coalesce(func.sum(InvoiceLine.quantity), 0).label("cases"),
            func.count(distinct(Invoice.id)).label("invoice_count"),
            func.count(distinct(Invoice.customer_id)).label("customer_count"),
        )
        .select_from(Invoice)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .join(Customer, Customer.id == Invoice.customer_id, isouter=True)
        .group_by(Customer.state_code)
        .order_by(func.sum(InvoiceLine.amount).desc())
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    return [
        {
            "state_code": row.state_code,
            "revenue": row.revenue,
            "cases": row.cases,
            "invoice_count": row.invoice_count,
            "customer_count": row.customer_count,
        }
        for row in (await session.execute(stmt)).all()
    ]


async def get_sales_by_distributor(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Return distributor-level aggregates sorted by revenue descending.

    Joins invoices → customers → distributors. Invoices whose customer
    has no distributor_id (yet) aggregate under
    ``distributor_id=None, distributor_name=None``.
    """
    clauses = _date_filter_clauses(date_from, date_to)

    stmt = (
        select(
            Distributor.id.label("distributor_id"),
            Distributor.name.label("distributor_name"),
            Distributor.channel.label("channel"),
            func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"),
            func.coalesce(func.sum(InvoiceLine.quantity), 0).label("cases"),
            func.count(distinct(Invoice.id)).label("invoice_count"),
            func.count(distinct(Invoice.customer_id)).label("customer_count"),
        )
        .select_from(Invoice)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .join(Customer, Customer.id == Invoice.customer_id, isouter=True)
        .join(Distributor, Distributor.id == Customer.distributor_id, isouter=True)
        .group_by(Distributor.id, Distributor.name, Distributor.channel)
        .order_by(func.sum(InvoiceLine.amount).desc())
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    return [
        {
            "distributor_id": row.distributor_id,
            "distributor_name": row.distributor_name,
            "channel": row.channel,
            "revenue": row.revenue,
            "cases": row.cases,
            "invoice_count": row.invoice_count,
            "customer_count": row.customer_count,
        }
        for row in (await session.execute(stmt)).all()
    ]
