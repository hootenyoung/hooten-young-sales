"""Read-side queries for the depletions API.

All queries support optional date-range filtering on
``depletions.period_month``. Negative case values (returns) flow through
naturally — ``SUM`` nets them out, which is the right business behavior.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import (
    Account,
    Depletion,
    Distributor,
    Product,
)


def _period_filter_clauses(date_from: date | None, date_to: date | None) -> list[Any]:
    clauses: list[Any] = []
    if date_from is not None:
        clauses.append(Depletion.period_month >= date_from)
    if date_to is not None:
        clauses.append(Depletion.period_month <= date_to)
    return clauses


async def get_depletions_kpis(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Compute top-line depletions KPIs for a date range."""
    clauses = _period_filter_clauses(date_from, date_to)

    stmt = (
        select(
            func.coalesce(func.sum(Depletion.cases_9l), 0).label("total_9l"),
            func.coalesce(func.sum(Depletion.cases_physical), 0).label("total_physical"),
            func.count(distinct(Depletion.account_id)).label("unique_accounts"),
            func.count(distinct(Depletion.product_id)).label("unique_products"),
            func.count(distinct(Account.state_code)).label("unique_states"),
            func.count(distinct(Account.distributor_id)).label("unique_distributors"),
            func.min(Depletion.period_month).label("period_start"),
            func.max(Depletion.period_month).label("period_end"),
        )
        .select_from(Depletion)
        .join(Account, Account.id == Depletion.account_id)
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    row = (await session.execute(stmt)).one()

    total_9l: Decimal = row.total_9l
    accounts: int = row.unique_accounts
    avg = (total_9l / accounts) if accounts > 0 else None

    return {
        "total_9l": total_9l,
        "total_physical": row.total_physical,
        "unique_accounts": accounts,
        "unique_products": row.unique_products,
        "unique_states": row.unique_states,
        "unique_distributors": row.unique_distributors,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "avg_9l_per_account": avg,
    }


async def get_depletions_monthly_trend(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Return monthly depletion volume, ascending by month."""
    clauses = _period_filter_clauses(date_from, date_to)

    month_bucket = func.date_trunc("month", Depletion.period_month).cast(Date).label("period")

    stmt = (
        select(
            month_bucket,
            func.coalesce(func.sum(Depletion.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(Depletion.cases_physical), 0).label("cases_physical"),
            func.count(distinct(Depletion.account_id)).label("active_accounts"),
        )
        .select_from(Depletion)
        .group_by(month_bucket)
        .order_by(month_bucket)
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    return [
        {
            "period": row.period,
            "cases_9l": row.cases_9l,
            "cases_physical": row.cases_physical,
            "active_accounts": row.active_accounts,
        }
        for row in (await session.execute(stmt)).all()
    ]


async def get_depletions_by_product(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Return product-level depletion aggregates sorted by 9L desc."""
    clauses = _period_filter_clauses(date_from, date_to)

    stmt = (
        select(
            Product.id.label("product_id"),
            Product.full_name.label("product_name"),
            func.coalesce(func.sum(Depletion.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(Depletion.cases_physical), 0).label("cases_physical"),
            func.count(distinct(Depletion.account_id)).label("account_count"),
            func.count(distinct(Account.state_code)).label("state_count"),
        )
        .select_from(Depletion)
        .join(Product, Product.id == Depletion.product_id)
        .join(Account, Account.id == Depletion.account_id)
        .group_by(Product.id, Product.full_name)
        .order_by(func.sum(Depletion.cases_9l).desc())
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    return [
        {
            "product_id": row.product_id,
            "product_name": row.product_name,
            "cases_9l": row.cases_9l,
            "cases_physical": row.cases_physical,
            "account_count": row.account_count,
            "state_count": row.state_count,
        }
        for row in (await session.execute(stmt)).all()
    ]


async def get_depletions_by_state(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Return state-level depletion aggregates sorted by 9L desc."""
    clauses = _period_filter_clauses(date_from, date_to)

    stmt = (
        select(
            Account.state_code.label("state_code"),
            func.coalesce(func.sum(Depletion.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(Depletion.cases_physical), 0).label("cases_physical"),
            func.count(distinct(Depletion.account_id)).label("account_count"),
        )
        .select_from(Depletion)
        .join(Account, Account.id == Depletion.account_id)
        .group_by(Account.state_code)
        .order_by(func.sum(Depletion.cases_9l).desc())
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    return [
        {
            "state_code": row.state_code,
            "cases_9l": row.cases_9l,
            "cases_physical": row.cases_physical,
            "account_count": row.account_count,
        }
        for row in (await session.execute(stmt)).all()
    ]


async def get_top_accounts(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return top accounts by 9L depletion volume, descending."""
    clauses = _period_filter_clauses(date_from, date_to)

    stmt = (
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Account.state_code.label("state_code"),
            Account.city.label("city"),
            Distributor.name.label("distributor_name"),
            func.coalesce(func.sum(Depletion.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(Depletion.cases_physical), 0).label("cases_physical"),
            func.count(distinct(Depletion.product_id)).label("product_count"),
            func.max(Depletion.period_month).label("last_active_period"),
        )
        .select_from(Depletion)
        .join(Account, Account.id == Depletion.account_id)
        .join(Distributor, Distributor.id == Account.distributor_id, isouter=True)
        .group_by(
            Account.id,
            Account.name,
            Account.state_code,
            Account.city,
            Distributor.name,
        )
        .order_by(func.sum(Depletion.cases_9l).desc())
        .limit(limit)
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    return [
        {
            "account_id": row.account_id,
            "name": row.name,
            "state_code": row.state_code,
            "city": row.city,
            "distributor_name": row.distributor_name,
            "cases_9l": row.cases_9l,
            "cases_physical": row.cases_physical,
            "product_count": row.product_count,
            "last_active_period": row.last_active_period,
        }
        for row in (await session.execute(stmt)).all()
    ]
