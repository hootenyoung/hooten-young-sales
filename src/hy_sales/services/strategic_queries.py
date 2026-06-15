"""Strategic / analytical queries for the sales (invoices) domain.

Covers:
  * White-Space Matrix — product x state revenue grid + gap statistics
    (sales-side only: invoices x products x customer states).
  * Order Analysis — invoice-level rollups (size buckets, cross-sell pairs,
    distributor frequency, monthly order trend).
  * Risk / Concentration — top-N share + Herfindahl-Hirschman Index across
    product, distributor, and state dimensions.

The depletions-side strategic queries (Follow-Up Tracker, New vs Lost,
Velocity) live in ``services.depletions_strategic`` — physically
isolated, no shared helpers or models.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any, TypedDict, cast

from sqlalchemy import Date, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import (
    Customer,
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
