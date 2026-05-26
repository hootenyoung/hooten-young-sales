"""Strategic / analytical queries that combine raw aggregates with extra Python logic.

Covers:
  * White-Space Matrix — product x state grid + gap statistics.
  * Order Analysis — invoice-level rollups (size buckets, cross-sell pairs,
    distributor frequency, monthly order trend).
  * Risk / Concentration — top-N share + Herfindahl-Hirschman Index across
    product, distributor, and state dimensions.
  * Follow-Up Tracker — accounts bucketed by days since last depletion.
  * New vs Lost Accounts — accounts gained / lost between two time windows.

These call into the simpler aggregations but layer on derived metrics that
don't compose cleanly as a single SQL query.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypedDict, cast

from sqlalchemy import Date, and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import (
    Account,
    Customer,
    Depletion,
    Distributor,
    Invoice,
    InvoiceLine,
    Product,
)


class _BucketDict(TypedDict):
    label: str
    min: float
    max: float | None
    count: int
    revenue: Decimal


# ----------------------------------------------------------------
# White-Space Matrix
# ----------------------------------------------------------------


async def get_white_space_matrix(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Build the product x state revenue matrix + gap stats.

    Returns:
      products: [{id, name, revenue}] sorted by revenue desc
      states:   [{code, revenue}] sorted by revenue desc
      cells:    [{product_id, state_code, revenue, cases}]  -- only non-zero combos
      total_combos / filled_combos / gap_count / gap_pct
    """
    clauses = []
    if date_from is not None:
        clauses.append(Invoice.invoice_date >= date_from)
    if date_to is not None:
        clauses.append(Invoice.invoice_date <= date_to)

    stmt = (
        select(
            Product.id.label("product_id"),
            Product.full_name.label("product_name"),
            Customer.state_code.label("state_code"),
            func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"),
            func.coalesce(func.sum(InvoiceLine.quantity), 0).label("cases"),
        )
        .select_from(InvoiceLine)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Product, Product.id == InvoiceLine.product_id)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(Customer.state_code.is_not(None))
        .group_by(Product.id, Product.full_name, Customer.state_code)
    )
    for clause in clauses:
        stmt = stmt.where(clause)

    rows = (await session.execute(stmt)).all()

    product_totals: dict[int, dict[str, Any]] = {}
    state_totals: dict[str, Decimal] = {}
    cells: list[dict[str, Any]] = []

    for row in rows:
        pid: int = row.product_id
        pname: str = row.product_name
        scode: str = row.state_code
        revenue: Decimal = row.revenue
        cases: Decimal = row.cases

        product_totals.setdefault(pid, {"id": pid, "name": pname, "revenue": Decimal("0")})
        product_totals[pid]["revenue"] += revenue

        state_totals[scode] = state_totals.get(scode, Decimal("0")) + revenue

        if revenue > 0 or cases > 0:
            cells.append(
                {
                    "product_id": pid,
                    "state_code": scode,
                    "revenue": revenue,
                    "cases": cases,
                }
            )

    products_sorted = sorted(
        product_totals.values(),
        key=lambda p: cast(Decimal, p["revenue"]),
        reverse=True,
    )
    states_sorted = sorted(
        ({"code": code, "revenue": rev} for code, rev in state_totals.items()),
        key=lambda s: cast(Decimal, s["revenue"]),
        reverse=True,
    )

    total_combos = len(products_sorted) * len(states_sorted)
    filled_combos = len(cells)
    gap_count = total_combos - filled_combos
    gap_pct = (gap_count / total_combos) if total_combos > 0 else 0.0

    return {
        "products": products_sorted,
        "states": states_sorted,
        "cells": cells,
        "total_combos": total_combos,
        "filled_combos": filled_combos,
        "gap_count": gap_count,
        "gap_pct": gap_pct,
    }


# ----------------------------------------------------------------
# Order Analysis
# ----------------------------------------------------------------


_ORDER_SIZE_BUCKETS: list[tuple[str, Decimal, Decimal | None]] = [
    ("Under $1K", Decimal("0"), Decimal("1000")),
    ("$1K-$3K", Decimal("1000"), Decimal("3000")),
    ("$3K-$5K", Decimal("3000"), Decimal("5000")),
    ("$5K-$10K", Decimal("5000"), Decimal("10000")),
    ("$10K-$25K", Decimal("10000"), Decimal("25000")),
    ("Over $25K", Decimal("25000"), None),
]


async def get_order_analysis(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Compute order-level rollups (size buckets, cross-sell pairs, etc.)."""
    clauses = []
    if date_from is not None:
        clauses.append(Invoice.invoice_date >= date_from)
    if date_to is not None:
        clauses.append(Invoice.invoice_date <= date_to)

    # Per-order rollup.
    order_stmt = (
        select(
            Invoice.id.label("invoice_id"),
            Invoice.invoice_ref.label("invoice_ref"),
            Invoice.invoice_date.label("invoice_date"),
            Distributor.id.label("distributor_id"),
            Distributor.name.label("distributor_name"),
            Customer.state_code.label("state_code"),
            func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"),
            func.coalesce(func.sum(InvoiceLine.quantity), 0).label("cases"),
            func.count(distinct(InvoiceLine.product_id)).label("product_count"),
        )
        .select_from(Invoice)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .join(Customer, Customer.id == Invoice.customer_id, isouter=True)
        .join(Distributor, Distributor.id == Customer.distributor_id, isouter=True)
        .group_by(
            Invoice.id,
            Invoice.invoice_ref,
            Invoice.invoice_date,
            Distributor.id,
            Distributor.name,
            Customer.state_code,
        )
    )
    for clause in clauses:
        order_stmt = order_stmt.where(clause)
    orders = (await session.execute(order_stmt)).all()

    # Size buckets.
    buckets: list[_BucketDict] = [
        {
            "label": label,
            "min": float(lo),
            "max": float(hi) if hi else None,
            "count": 0,
            "revenue": Decimal("0"),
        }
        for label, lo, hi in _ORDER_SIZE_BUCKETS
    ]
    revenues: list[Decimal] = []
    multi_revenues: list[Decimal] = []
    single_revenues: list[Decimal] = []
    for order in orders:
        rev: Decimal = order.revenue
        revenues.append(rev)
        for bucket, (_label, lo, hi) in zip(buckets, _ORDER_SIZE_BUCKETS, strict=True):
            if rev >= lo and (hi is None or rev < hi):
                bucket["count"] += 1
                bucket["revenue"] += rev
                break
        if order.product_count > 1:
            multi_revenues.append(rev)
        else:
            single_revenues.append(rev)

    total_orders = len(orders)
    total_revenue = sum(revenues, Decimal("0"))
    avg_order_value = (total_revenue / total_orders) if total_orders > 0 else Decimal("0")
    median_order_value = sorted(revenues)[len(revenues) // 2] if revenues else Decimal("0")
    avg_multi = (
        sum(multi_revenues, Decimal("0")) / len(multi_revenues) if multi_revenues else Decimal("0")
    )
    avg_single = (
        sum(single_revenues, Decimal("0")) / len(single_revenues)
        if single_revenues
        else Decimal("0")
    )

    # Cross-sell: top product pairs from multi-product invoices.
    multi_ids = [o.invoice_id for o in orders if o.product_count > 1]
    pair_counts: Counter[tuple[int, int]] = Counter()
    pair_names: dict[tuple[int, int], tuple[str, str]] = {}
    if multi_ids:
        prod_stmt = (
            select(
                InvoiceLine.invoice_id,
                Product.id.label("product_id"),
                Product.full_name.label("product_name"),
            )
            .join(Product, Product.id == InvoiceLine.product_id)
            .where(InvoiceLine.invoice_id.in_(multi_ids))
        )
        invoice_products: dict[int, list[tuple[int, str]]] = {}
        for row in (await session.execute(prod_stmt)).all():
            invoice_products.setdefault(row.invoice_id, []).append(
                (row.product_id, row.product_name)
            )
        for products in invoice_products.values():
            unique = sorted(set(products), key=lambda p: p[0])
            for i in range(len(unique)):
                for j in range(i + 1, len(unique)):
                    a, b = unique[i], unique[j]
                    key = (a[0], b[0])
                    pair_counts[key] += 1
                    pair_names[key] = (a[1], b[1])
    top_pairs = [
        {
            "product_a_id": k[0],
            "product_a_name": pair_names[k][0],
            "product_b_id": k[1],
            "product_b_name": pair_names[k][1],
            "count": v,
        }
        for k, v in pair_counts.most_common(5)
    ]

    # Distributor reorder frequency.
    dist_orders: dict[int | None, dict[str, Any]] = {}
    for order in orders:
        did = order.distributor_id
        slot = dist_orders.setdefault(
            did,
            {
                "distributor_id": did,
                "distributor_name": order.distributor_name,
                "order_count": 0,
                "total_revenue": Decimal("0"),
            },
        )
        slot["order_count"] += 1
        slot["total_revenue"] += order.revenue
    distributor_frequency = sorted(
        (
            {
                **slot,
                "avg_order_value": (
                    slot["total_revenue"] / slot["order_count"]
                    if slot["order_count"] > 0
                    else Decimal("0")
                ),
            }
            for slot in dist_orders.values()
        ),
        key=lambda d: d["order_count"],
        reverse=True,
    )
    repeat_buyers = sum(1 for d in distributor_frequency if d["order_count"] > 1)
    one_time_buyers = sum(1 for d in distributor_frequency if d["order_count"] == 1)

    # Monthly order trend.
    monthly_stmt = (
        select(
            func.date_trunc("month", Invoice.invoice_date).cast(Date).label("period"),
            func.count(distinct(Invoice.id)).label("orders"),
            func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"),
        )
        .select_from(Invoice)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .group_by(func.date_trunc("month", Invoice.invoice_date).cast(Date))
        .order_by(func.date_trunc("month", Invoice.invoice_date).cast(Date))
    )
    for clause in clauses:
        monthly_stmt = monthly_stmt.where(clause)
    monthly_orders = [
        {
            "period": row.period,
            "orders": row.orders,
            "revenue": row.revenue,
            "avg_value": (row.revenue / row.orders) if row.orders > 0 else Decimal("0"),
        }
        for row in (await session.execute(monthly_stmt)).all()
    ]

    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "avg_order_value": avg_order_value,
        "median_order_value": median_order_value,
        "size_buckets": buckets,
        "multi_product_orders": len(multi_revenues),
        "single_product_orders": len(single_revenues),
        "avg_multi_value": avg_multi,
        "avg_single_value": avg_single,
        "top_product_pairs": top_pairs,
        "distributor_frequency": distributor_frequency,
        "repeat_buyers": repeat_buyers,
        "one_time_buyers": one_time_buyers,
        "monthly_orders": monthly_orders,
    }


# ----------------------------------------------------------------
# Risk / Concentration
# ----------------------------------------------------------------


def _concentration(values: list[Decimal]) -> dict[str, Any]:
    """Return top-N share + HHI for a list of revenue values."""
    sorted_values = sorted(values, reverse=True)
    total = sum(sorted_values, Decimal("0"))
    if total == 0:
        return {
            "top_1_share": 0.0,
            "top_3_share": 0.0,
            "top_5_share": 0.0,
            "hhi": 0.0,
            "entry_count": len(sorted_values),
        }
    top1 = sum(sorted_values[:1], Decimal("0"))
    top3 = sum(sorted_values[:3], Decimal("0"))
    top5 = sum(sorted_values[:5], Decimal("0"))
    # HHI as sum of squared shares scaled to 0..10000.
    hhi = sum((float(v / total) * 100) ** 2 for v in sorted_values)
    return {
        "top_1_share": float(top1 / total),
        "top_3_share": float(top3 / total),
        "top_5_share": float(top5 / total),
        "hhi": hhi,
        "entry_count": len(sorted_values),
    }


async def get_risk_dashboard(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Compute concentration metrics across product, distributor, state."""
    clauses = []
    if date_from is not None:
        clauses.append(Invoice.invoice_date >= date_from)
    if date_to is not None:
        clauses.append(Invoice.invoice_date <= date_to)

    async def _dim_revenue(group_col: Any) -> list[Decimal]:
        stmt = (
            select(func.coalesce(func.sum(InvoiceLine.amount), 0).label("revenue"))
            .select_from(InvoiceLine)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .join(Customer, Customer.id == Invoice.customer_id, isouter=True)
            .join(Distributor, Distributor.id == Customer.distributor_id, isouter=True)
            .group_by(group_col)
        )
        for clause in clauses:
            stmt = stmt.where(clause)
        return [row.revenue for row in (await session.execute(stmt)).all() if row.revenue > 0]

    products = await _dim_revenue(InvoiceLine.product_id)
    distributors = await _dim_revenue(Distributor.id)
    states = await _dim_revenue(Customer.state_code)

    return {
        "product_concentration": _concentration(products),
        "distributor_concentration": _concentration(distributors),
        "state_concentration": _concentration(states),
    }


# ----------------------------------------------------------------
# Follow-Up Tracker (depletions)
# ----------------------------------------------------------------


_FOLLOW_UP_BUCKETS = [
    ("0-30 days", 0, 30),
    ("30-60 days", 30, 60),
    ("60-90 days", 60, 90),
    ("90-120 days", 90, 120),
    ("120+ days", 120, None),
]


async def get_follow_up_tracker(
    session: AsyncSession,
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Bucket accounts by days since their last recorded depletion.

    ``reference_date`` defaults to the latest period_month in the data
    (treated as "today" for the analysis). Each bucket reports a count
    plus the accounts that fall in it.
    """
    latest_stmt = select(func.max(Depletion.period_month))
    latest: date | None = await session.scalar(latest_stmt)
    ref: date = reference_date or latest or date.today()

    stmt = (
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Account.state_code.label("state_code"),
            Account.city.label("city"),
            Distributor.name.label("distributor_name"),
            func.max(Depletion.period_month).label("last_active"),
            func.coalesce(func.sum(Depletion.cases_9l), 0).label("total_9l"),
            func.count(distinct(Depletion.product_id)).label("product_count"),
        )
        .select_from(Account)
        .join(Depletion, Depletion.account_id == Account.id)
        .join(Distributor, Distributor.id == Account.distributor_id, isouter=True)
        .group_by(
            Account.id,
            Account.name,
            Account.state_code,
            Account.city,
            Distributor.name,
        )
    )
    rows = (await session.execute(stmt)).all()

    buckets: dict[str, dict[str, Any]] = {
        name: {"label": name, "count": 0, "total_9l": Decimal("0"), "accounts": []}
        for name, _lo, _hi in _FOLLOW_UP_BUCKETS
    }
    for row in rows:
        last_active: date = row.last_active
        days = (ref - last_active).days
        bucket_name: str | None = None
        for name, lo, hi in _FOLLOW_UP_BUCKETS:
            if days >= lo and (hi is None or days < hi):
                bucket_name = name
                break
        if bucket_name is None:
            continue
        bucket = buckets[bucket_name]
        bucket["count"] += 1
        bucket["total_9l"] += row.total_9l
        bucket["accounts"].append(
            {
                "account_id": row.account_id,
                "name": row.name,
                "state_code": row.state_code,
                "city": row.city,
                "distributor_name": row.distributor_name,
                "last_active": last_active,
                "days_since": days,
                "total_9l": row.total_9l,
                "product_count": row.product_count,
            }
        )

    # Sort accounts within each bucket by days_since asc (most recent first).
    for bucket in buckets.values():
        bucket["accounts"].sort(key=lambda a: a["days_since"])

    return {
        "reference_date": ref,
        "buckets": list(buckets.values()),
    }


# ----------------------------------------------------------------
# New vs Lost Accounts (depletions)
# ----------------------------------------------------------------


async def get_new_vs_lost_accounts(
    session: AsyncSession,
    *,
    window_months: int = 3,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Compare account activity in two adjacent windows.

    Recent window: ``[ref - 2*window, ref]`` -- last 3 months by default.
    Prior window:  ``[ref - 4*window, ref - window]`` -- 3 months before.

    Accounts active in recent but not prior = NEW.
    Accounts active in prior but not recent = LOST.
    Both buckets include the account's volume in their respective window.
    """
    latest: date | None = await session.scalar(select(func.max(Depletion.period_month)))
    ref: date = reference_date or latest or date.today()

    # Period boundaries -- approximate "months" as 30 days, since
    # we're aligning to the first-of-month rule on Depletion.period_month.
    recent_from = ref - timedelta(days=window_months * 31)
    prior_from = recent_from - timedelta(days=window_months * 31)
    prior_to = recent_from

    def _window_query(start: date, end: date) -> Any:
        return (
            select(
                Account.id.label("account_id"),
                Account.name.label("name"),
                Account.state_code.label("state_code"),
                Account.city.label("city"),
                Distributor.name.label("distributor_name"),
                func.coalesce(func.sum(Depletion.cases_9l), 0).label("cases_9l"),
            )
            .select_from(Account)
            .join(Depletion, Depletion.account_id == Account.id)
            .join(Distributor, Distributor.id == Account.distributor_id, isouter=True)
            .where(and_(Depletion.period_month >= start, Depletion.period_month < end))
            .group_by(Account.id, Account.name, Account.state_code, Account.city, Distributor.name)
        )

    recent_result = await session.execute(_window_query(recent_from, ref + timedelta(days=1)))
    recent_rows = {row.account_id: row for row in recent_result.all()}
    prior_result = await session.execute(_window_query(prior_from, prior_to))
    prior_rows = {row.account_id: row for row in prior_result.all()}

    new_ids = set(recent_rows) - set(prior_rows)
    lost_ids = set(prior_rows) - set(recent_rows)

    def _to_dict(row: Any, cases: Decimal) -> dict[str, Any]:
        return {
            "account_id": row.account_id,
            "name": row.name,
            "state_code": row.state_code,
            "city": row.city,
            "distributor_name": row.distributor_name,
            "cases_9l": cases,
        }

    new_accounts = [_to_dict(recent_rows[aid], recent_rows[aid].cases_9l) for aid in new_ids]
    new_accounts.sort(key=lambda a: a["cases_9l"], reverse=True)

    lost_accounts = [_to_dict(prior_rows[aid], prior_rows[aid].cases_9l) for aid in lost_ids]
    lost_accounts.sort(key=lambda a: a["cases_9l"], reverse=True)

    return {
        "reference_date": ref,
        "window_months": window_months,
        "recent_window_start": recent_from,
        "prior_window_start": prior_from,
        "prior_window_end": prior_to,
        "new_accounts": new_accounts,
        "lost_accounts": lost_accounts,
        "new_count": len(new_accounts),
        "lost_count": len(lost_accounts),
        "new_total_9l": sum((a["cases_9l"] for a in new_accounts), Decimal("0")),
        "lost_total_9l": sum((a["cases_9l"] for a in lost_accounts), Decimal("0")),
    }


# ----------------------------------------------------------------
# Velocity Analysis (depletions)
# ----------------------------------------------------------------


def _classify_velocity(
    recent_avg: Decimal,
    prior_avg: Decimal,
    months_active: int,
) -> tuple[float | None, str]:
    """Return (velocity_change_pct, category)."""
    if recent_avg == 0 and prior_avg == 0:
        return None, "silent"
    if prior_avg == 0:
        return None, "new"
    change = float((recent_avg - prior_avg) / prior_avg)
    pct = change * 100
    if months_active < 3:
        return pct, "new"
    if pct > 20:
        return pct, "accelerating"
    if pct < -20:
        return pct, "declining"
    return pct, "steady"


async def get_velocity_analysis(
    session: AsyncSession,
    *,
    recent_window_months: int = 3,
) -> dict[str, Any]:
    """Compute per-account depletion velocity over the available history."""
    latest: date | None = await session.scalar(select(func.max(Depletion.period_month)))
    ref: date = latest or date.today()
    recent_cutoff = ref - timedelta(days=recent_window_months * 31)
    prior_cutoff = recent_cutoff - timedelta(days=recent_window_months * 31)

    stmt = (
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Account.state_code.label("state_code"),
            Account.city.label("city"),
            Distributor.name.label("distributor_name"),
            Depletion.period_month.label("period_month"),
            func.coalesce(func.sum(Depletion.cases_9l), 0).label("cases_9l"),
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
            Depletion.period_month,
        )
    )
    rows = (await session.execute(stmt)).all()

    by_account: dict[int, dict[str, Any]] = {}
    for row in rows:
        slot = by_account.setdefault(
            row.account_id,
            {
                "account_id": row.account_id,
                "name": row.name,
                "state_code": row.state_code,
                "city": row.city,
                "distributor_name": row.distributor_name,
                "points": [],
            },
        )
        slot["points"].append((row.period_month, row.cases_9l))

    accounts: list[dict[str, Any]] = []
    category_totals: dict[str, dict[str, Any]] = {}
    for slot in by_account.values():
        points: list[tuple[date, Decimal]] = slot["points"]
        months_active = len(points)
        total_9l = sum((p[1] for p in points), Decimal("0"))
        avg = (total_9l / months_active) if months_active > 0 else Decimal("0")
        recent_pts = [p[1] for p in points if p[0] >= recent_cutoff]
        prior_pts = [p[1] for p in points if prior_cutoff <= p[0] < recent_cutoff]
        recent_avg = sum(recent_pts, Decimal("0")) / len(recent_pts) if recent_pts else Decimal("0")
        prior_avg = sum(prior_pts, Decimal("0")) / len(prior_pts) if prior_pts else Decimal("0")
        pct, category = _classify_velocity(recent_avg, prior_avg, months_active)

        accounts.append(
            {
                "account_id": slot["account_id"],
                "name": slot["name"],
                "state_code": slot["state_code"],
                "city": slot["city"],
                "distributor_name": slot["distributor_name"],
                "months_active": months_active,
                "total_9l": total_9l,
                "avg_9l_per_month": avg,
                "recent_3m_avg": recent_avg,
                "prior_3m_avg": prior_avg,
                "velocity_change_pct": pct,
                "category": category,
            }
        )

        cat_slot = category_totals.setdefault(
            category, {"category": category, "count": 0, "total_9l": Decimal("0")}
        )
        cat_slot["count"] += 1
        cat_slot["total_9l"] += total_9l

    accounts.sort(key=lambda a: cast(Decimal, a["total_9l"]), reverse=True)

    category_order = ["accelerating", "steady", "declining", "new", "silent"]
    category_stats = [category_totals[c] for c in category_order if c in category_totals]

    return {
        "reference_date": ref,
        "accounts": accounts,
        "category_stats": category_stats,
    }
