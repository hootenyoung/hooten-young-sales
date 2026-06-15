"""Read-side queries for the depletions API.

All queries support optional date-range filtering on
``DepFact.period_month``. Negative case values (returns) flow through
naturally — ``SUM`` nets them out, which is the right business behavior.

Queries here only touch the ``depletions`` schema — there is no cross
to ``sales``. The depletions feed carries a raw distributor short code
(e.g. ``"FL13"``) on each account; there is no canonical distributor
entity for the depletions side. Distributor breakdowns use the code as
the grouping key.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import (
    DepAccount,
    DepFact,
    DepProduct,
)


def _period_filter_clauses(date_from: date | None, date_to: date | None) -> list[Any]:
    clauses: list[Any] = []
    if date_from is not None:
        clauses.append(DepFact.period_month >= date_from)
    if date_to is not None:
        clauses.append(DepFact.period_month <= date_to)
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
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("total_9l"),
            func.coalesce(func.sum(DepFact.cases_physical), 0).label("total_physical"),
            func.count(distinct(DepFact.account_id)).label("unique_accounts"),
            func.count(distinct(DepFact.product_id)).label("unique_products"),
            func.count(distinct(DepAccount.state_code)).label("unique_states"),
            func.count(distinct(DepAccount.distributor_code)).label("unique_distributors"),
            func.min(DepFact.period_month).label("period_start"),
            func.max(DepFact.period_month).label("period_end"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
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

    month_bucket = func.date_trunc("month", DepFact.period_month).cast(Date).label("period")

    # "Active" means the account moved product that month. Zero-volume
    # rows do exist (iDIG explicitly reports zero for every (account,
    # product, month) cell, which we preserve) but they shouldn't count
    # as activity. Filter at COUNT-time via a CASE so SUM is unaffected.
    active_account_expr = func.count(
        distinct(case((DepFact.cases_9l != 0, DepFact.account_id)))
    ).label("active_accounts")

    stmt = (
        select(
            month_bucket,
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(DepFact.cases_physical), 0).label("cases_physical"),
            active_account_expr,
        )
        .select_from(DepFact)
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
            DepProduct.id.label("product_id"),
            DepProduct.full_name.label("product_name"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(DepFact.cases_physical), 0).label("cases_physical"),
            func.count(distinct(DepFact.account_id)).label("account_count"),
            func.count(distinct(DepAccount.state_code)).label("state_count"),
        )
        .select_from(DepFact)
        .join(DepProduct, DepProduct.id == DepFact.product_id)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(DepProduct.id, DepProduct.full_name)
        .order_by(func.sum(DepFact.cases_9l).desc())
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
            DepAccount.state_code.label("state_code"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(DepFact.cases_physical), 0).label("cases_physical"),
            func.count(distinct(DepFact.account_id)).label("account_count"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(DepAccount.state_code)
        .order_by(func.sum(DepFact.cases_9l).desc())
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


async def get_account_monthly_grid(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return top N accounts by total 9L with their full monthly volume series.

    Powers the depletions heatmap (top accounts x month-grid intensity).
    The frequency classification is derived purely from active-month
    count and matches the MVP's bucketing:

        Monthly      >= 12 active months
        Bi-Monthly   >=  6 active months
        Quarterly    >=  3 active months
        Infrequent    <  3 active months

    "Active" means a row with cases_9l != 0 (zero-volume rows exist
    because iDIG reports a row for every (account, product, month)
    combination — those don't count as activity).
    """
    clauses = _period_filter_clauses(date_from, date_to)

    period_range = (
        await session.execute(
            select(
                func.min(DepFact.period_month).label("period_start"),
                func.max(DepFact.period_month).label("period_end"),
            ).select_from(DepFact)
        )
    ).one()
    if period_range.period_start is None:
        return {
            "months": [],
            "accounts": [],
            "period_start": None,
            "period_end": None,
        }

    # Top N accounts overall (filter applies).
    top_stmt = (
        select(
            DepAccount.id.label("account_id"),
            DepAccount.name.label("name"),
            DepAccount.address.label("address"),
            DepAccount.state_code.label("state_code"),
            DepAccount.city.label("city"),
            DepAccount.county.label("county"),
            DepAccount.zip_code.label("zip_code"),
            DepAccount.distributor_code.label("distributor_code"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("total_9l"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(
            DepAccount.id,
            DepAccount.name,
            DepAccount.address,
            DepAccount.state_code,
            DepAccount.city,
            DepAccount.county,
            DepAccount.zip_code,
            DepAccount.distributor_code,
        )
        .order_by(func.sum(DepFact.cases_9l).desc())
        .limit(limit)
    )
    for clause in clauses:
        top_stmt = top_stmt.where(clause)
    top_rows = (await session.execute(top_stmt)).all()
    top_ids = [r.account_id for r in top_rows]

    if not top_ids:
        return {
            "months": [],
            "accounts": [],
            "period_start": period_range.period_start,
            "period_end": period_range.period_end,
        }

    # Pull each top account's monthly series in ONE query.
    grid_stmt = (
        select(
            DepFact.account_id.label("account_id"),
            DepFact.period_month.label("period_month"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
        )
        .select_from(DepFact)
        .where(DepFact.account_id.in_(top_ids))
        .group_by(DepFact.account_id, DepFact.period_month)
    )
    for clause in clauses:
        grid_stmt = grid_stmt.where(clause)
    grid_rows = (await session.execute(grid_stmt)).all()

    # Pass 2 — per-(account, product, month) breakdown for the SAME
    # top accounts. Only non-zero cells are returned so the response
    # payload doesn't carry empty product lists for silent months.
    # Powers the heatmap's cell-hover tooltip ("what did they actually
    # order in Jul '25?").
    breakdown_stmt = (
        select(
            DepFact.account_id.label("account_id"),
            DepFact.period_month.label("period_month"),
            DepFact.product_id.label("product_id"),
            DepProduct.full_name.label("product_name"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
        )
        .select_from(DepFact)
        .join(DepProduct, DepProduct.id == DepFact.product_id)
        .where(DepFact.account_id.in_(top_ids))
        .where(DepFact.cases_9l != 0)
        .group_by(
            DepFact.account_id,
            DepFact.period_month,
            DepFact.product_id,
            DepProduct.full_name,
        )
        .order_by(DepFact.account_id, DepFact.period_month, func.sum(DepFact.cases_9l).desc())
    )
    for clause in clauses:
        breakdown_stmt = breakdown_stmt.where(clause)
    breakdown_rows = (await session.execute(breakdown_stmt)).all()
    breakdown_by_cell: dict[tuple[int, date], list[dict[str, Any]]] = {}
    for r in breakdown_rows:
        key = (r.account_id, r.period_month)
        breakdown_by_cell.setdefault(key, []).append(
            {
                "product_id": r.product_id,
                "product_name": r.product_name,
                "cases_9l": r.cases_9l,
            }
        )

    # Build dense series per account and the unified month axis.
    by_account: dict[int, dict[date, Decimal]] = {aid: {} for aid in top_ids}
    months_seen: set[date] = set()
    for row in grid_rows:
        by_account[row.account_id][row.period_month] = row.cases_9l
        months_seen.add(row.period_month)
    months = sorted(months_seen)

    def _frequency(active: int) -> str:
        if active >= 12:
            return "Monthly"
        if active >= 6:
            return "Bi-Monthly"
        if active >= 3:
            return "Quarterly"
        return "Infrequent"

    accounts_out: list[dict[str, Any]] = []
    for top in top_rows:
        series = by_account[top.account_id]
        active = sum(1 for v in series.values() if v != 0)
        accounts_out.append(
            {
                "account_id": top.account_id,
                "name": top.name,
                "address": top.address,
                "state_code": top.state_code,
                "city": top.city,
                "county": top.county,
                "zip_code": top.zip_code,
                "distributor_code": top.distributor_code,
                "total_9l": top.total_9l,
                "months_active": active,
                "frequency": _frequency(active),
                "monthly_volumes": [
                    {
                        "period": m,
                        "cases_9l": series.get(m, Decimal("0")),
                        "products": breakdown_by_cell.get((top.account_id, m), []),
                    }
                    for m in months
                ],
            }
        )

    return {
        "months": months,
        "accounts": accounts_out,
        "period_start": period_range.period_start,
        "period_end": period_range.period_end,
    }


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
            DepAccount.id.label("account_id"),
            DepAccount.name.label("name"),
            DepAccount.state_code.label("state_code"),
            DepAccount.city.label("city"),
            DepAccount.distributor_code.label("distributor_code"),
            DepAccount.premises_type.label("premises_type"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(DepFact.cases_physical), 0).label("cases_physical"),
            func.count(distinct(DepFact.product_id)).label("product_count"),
            func.max(DepFact.period_month).label("last_active_period"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(
            DepAccount.id,
            DepAccount.name,
            DepAccount.state_code,
            DepAccount.city,
            DepAccount.distributor_code,
            DepAccount.premises_type,
        )
        .order_by(func.sum(DepFact.cases_9l).desc())
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
            "distributor_code": row.distributor_code,
            "premises_type": row.premises_type,
            "cases_9l": row.cases_9l,
            "cases_physical": row.cases_physical,
            "product_count": row.product_count,
            "last_active_period": row.last_active_period,
        }
        for row in (await session.execute(stmt)).all()
    ]
