"""Depletions-only strategic / analytical queries.

Bucketed views and trend classifications that ride entirely on top of
``depletions`` schema data — Follow-Up Tracker, New vs Lost Accounts,
Velocity Analysis. The previous ``strategic_queries`` module mixed
these with sales-side analytics; this file holds the depletions-only
half so it can be modified without risking sales-side breakage.

Distributor identity:
  These responses surface ``distributor_code`` (the raw short code from
  iDIG, e.g. ``"FL13"``). The Pydantic response schemas still expose
  the field as ``distributor_name`` — the code is passed through that
  field for API stability. Re-introduce a canonical distributor entity
  later if/when we have a reliable name source for the depletions feed.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import DepAccount, DepFact, DepProduct

_FOLLOW_UP_BUCKETS = [
    ("0-30 days", 0, 30),
    ("30-60 days", 30, 60),
    ("60-90 days", 60, 90),
    ("90-120 days", 90, 120),
    ("120+ days", 120, None),
]


# ----------------------------------------------------------------
# Follow-Up Tracker
# ----------------------------------------------------------------


async def get_follow_up_tracker(
    session: AsyncSession,
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Bucket accounts by days since their last non-zero depletion.

    ``reference_date`` defaults to the latest period_month in the data.
    Zero-volume periods do not count as "active" — we look for the last
    month the account moved any product.
    """
    latest: date | None = await session.scalar(select(func.max(DepFact.period_month)))
    ref: date = reference_date or latest or date.today()

    # The reference's first-of-month is the latest cell on the 12-month
    # sparkline. month_axis runs 12 months back, ascending.
    ref_month_start = date(ref.year, ref.month, 1)
    month_axis: list[date] = []
    y, m = ref_month_start.year, ref_month_start.month
    for i in range(11, -1, -1):
        nm = m - i
        ny = y
        while nm <= 0:
            nm += 12
            ny -= 1
        month_axis.append(date(ny, nm, 1))
    earliest_month = month_axis[0]

    # Pass 1 — one row per account with summary aggregates + the full
    # mailing-address fields. The address/county/zip are surfaced in
    # the UI's location hover tooltip — useful for territory planning
    # and confirming the right venue before a call.
    stmt = (
        select(
            DepAccount.id.label("account_id"),
            DepAccount.name.label("name"),
            DepAccount.address.label("address"),
            DepAccount.state_code.label("state_code"),
            DepAccount.city.label("city"),
            DepAccount.county.label("county"),
            DepAccount.zip_code.label("zip_code"),
            DepAccount.distributor_code.label("distributor_code"),
            func.max(DepFact.period_month).label("last_active"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("total_9l"),
            func.count(distinct(DepFact.product_id)).label("product_count"),
        )
        .select_from(DepAccount)
        .join(DepFact, DepFact.account_id == DepAccount.id)
        .where(DepFact.cases_9l != 0)
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
    )
    rows = (await session.execute(stmt)).all()

    # Pass 2 — collect per-account product short-name lists so the UI
    # can render chips like "Rye · Bottled in B · +1". Sorted by total
    # 9L per product so the most-bought product appears first.
    products_stmt = (
        select(
            DepFact.account_id.label("account_id"),
            DepProduct.full_name.label("product_name"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("product_9l"),
        )
        .select_from(DepFact)
        .join(DepProduct, DepProduct.id == DepFact.product_id)
        .where(DepFact.cases_9l != 0)
        .group_by(DepFact.account_id, DepProduct.full_name)
        .order_by(DepFact.account_id, func.sum(DepFact.cases_9l).desc())
    )
    products_by_account: dict[int, list[str]] = {}
    for prod_row in (await session.execute(products_stmt)).all():
        products_by_account.setdefault(prod_row.account_id, []).append(
            _short_product_name(prod_row.product_name)
        )

    # Pass 3 — first non-zero month per account ("customer since").
    since_stmt = (
        select(
            DepFact.account_id.label("account_id"),
            func.min(DepFact.period_month).label("first_active"),
        )
        .where(DepFact.cases_9l != 0)
        .group_by(DepFact.account_id)
    )
    customer_since_by_account: dict[int, date] = {
        s.account_id: s.first_active for s in (await session.execute(since_stmt)).all()
    }

    # Pass 4 — 12-month monthly volume series per account. Powers the
    # row sparkline AND the recent-3M vs prior-3M velocity chip.
    series_stmt = (
        select(
            DepFact.account_id.label("account_id"),
            DepFact.period_month.label("period_month"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
        )
        .select_from(DepFact)
        .where(DepFact.period_month >= earliest_month)
        .group_by(DepFact.account_id, DepFact.period_month)
    )
    series_by_account: dict[int, dict[date, Decimal]] = {}
    for srow in (await session.execute(series_stmt)).all():
        series_by_account.setdefault(srow.account_id, {})[srow.period_month] = srow.cases_9l

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
        series_dict = series_by_account.get(row.account_id, {})
        series_values: list[Decimal] = [series_dict.get(m, Decimal("0")) for m in month_axis]
        monthly_series = [
            {"period": m, "cases_9l": v} for m, v in zip(month_axis, series_values, strict=True)
        ]
        recent_3m_9l = sum(series_values[-3:], Decimal("0"))
        prior_3m_9l = sum(series_values[-6:-3], Decimal("0"))
        velocity_pct: float | None = None
        if prior_3m_9l > 0:
            velocity_pct = float((recent_3m_9l - prior_3m_9l) / prior_3m_9l * 100)

        customer_since = customer_since_by_account.get(row.account_id)
        customer_since_label = _month_label(customer_since) if customer_since else None

        bucket["accounts"].append(
            {
                "account_id": row.account_id,
                "name": row.name,
                "address": row.address,
                "state_code": row.state_code,
                "city": row.city,
                "county": row.county,
                "zip_code": row.zip_code,
                "distributor_name": row.distributor_code,
                "last_active": last_active,
                "last_active_label": _month_label(last_active),
                "days_since": days,
                "total_9l": row.total_9l,
                "product_count": row.product_count,
                "products": products_by_account.get(row.account_id, []),
                "customer_since": customer_since,
                "customer_since_label": customer_since_label,
                "recent_3m_9l": recent_3m_9l,
                "prior_3m_9l": prior_3m_9l,
                "velocity_pct": velocity_pct,
                "monthly_series": monthly_series,
            }
        )

    for bucket in buckets.values():
        bucket["accounts"].sort(key=lambda a: a["days_since"])

    return {
        "reference_date": ref,
        "buckets": list(buckets.values()),
    }


def _short_product_name(full: str) -> str:
    """Strip the brand prefix so chips fit nicely (e.g. "Hooten Young Rye" -> "Rye")."""
    for prefix in ("Hooten Young ", "Hooten & Young ", "Hooten and Young "):
        if full.startswith(prefix):
            return full[len(prefix) :].strip()
    return full


_MONTH_NAMES = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def _month_label(d: date) -> str:
    """Compact human label, e.g. ``Mar 2026``."""
    return f"{_MONTH_NAMES[d.month - 1]} {d.year}"


# ----------------------------------------------------------------
# New vs Lost Accounts
# ----------------------------------------------------------------


async def get_new_vs_lost_accounts(
    session: AsyncSession,
    *,
    window_months: int = 3,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Compare account activity in two adjacent windows.

    Recent window: ``[ref - window, ref]``. Prior window:
    ``[ref - 2*window, ref - window]``. Active in recent but not prior
    = NEW. Active in prior but not recent = LOST.
    """
    latest: date | None = await session.scalar(select(func.max(DepFact.period_month)))
    ref: date = reference_date or latest or date.today()

    recent_from = ref - timedelta(days=window_months * 31)
    prior_from = recent_from - timedelta(days=window_months * 31)
    prior_to = recent_from

    def _window_query(start: date, end: date) -> Any:
        return (
            select(
                DepAccount.id.label("account_id"),
                DepAccount.name.label("name"),
                DepAccount.state_code.label("state_code"),
                DepAccount.city.label("city"),
                DepAccount.distributor_code.label("distributor_code"),
                func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
            )
            .select_from(DepAccount)
            .join(DepFact, DepFact.account_id == DepAccount.id)
            .where(
                and_(
                    DepFact.period_month >= start,
                    DepFact.period_month < end,
                    DepFact.cases_9l != 0,
                )
            )
            .group_by(
                DepAccount.id,
                DepAccount.name,
                DepAccount.state_code,
                DepAccount.city,
                DepAccount.distributor_code,
            )
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
            "distributor_name": row.distributor_code,
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
# Growth & Decline (returning accounts)
# ----------------------------------------------------------------


async def get_growth_decline(
    session: AsyncSession,
    *,
    window_months: int = 12,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Compare per-account volume across two adjacent windows.

    Recent window: ``[ref - window, ref]``. Prior window:
    ``[ref - 2*window, ref - window]``. Only accounts active in BOTH
    windows are returned — this answers "of the customers we already
    have, who's growing vs shrinking?" (orthogonal to New-vs-Lost which
    catches base changes).

    Diff = recent_volume - prior_volume. Growing = diff > 0, Declining
    = diff < 0. Zero-diff accounts are dropped.
    """
    latest: date | None = await session.scalar(select(func.max(DepFact.period_month)))
    ref: date = reference_date or latest or date.today()

    recent_from = ref - timedelta(days=window_months * 31)
    prior_from = recent_from - timedelta(days=window_months * 31)
    prior_to = recent_from

    def _window_query(start: date, end: date) -> Any:
        return (
            select(
                DepAccount.id.label("account_id"),
                DepAccount.name.label("name"),
                DepAccount.state_code.label("state_code"),
                DepAccount.city.label("city"),
                DepAccount.distributor_code.label("distributor_code"),
                func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
            )
            .select_from(DepAccount)
            .join(DepFact, DepFact.account_id == DepAccount.id)
            .where(
                and_(
                    DepFact.period_month >= start,
                    DepFact.period_month < end,
                    DepFact.cases_9l != 0,
                )
            )
            .group_by(
                DepAccount.id,
                DepAccount.name,
                DepAccount.state_code,
                DepAccount.city,
                DepAccount.distributor_code,
            )
        )

    recent_rows = {
        row.account_id: row
        for row in (
            await session.execute(_window_query(recent_from, ref + timedelta(days=1)))
        ).all()
    }
    prior_rows = {
        row.account_id: row
        for row in (await session.execute(_window_query(prior_from, prior_to))).all()
    }

    # Returning = present in BOTH windows.
    returning_ids = set(recent_rows) & set(prior_rows)

    growing: list[dict[str, Any]] = []
    declining: list[dict[str, Any]] = []
    growing_total = Decimal("0")
    declining_total = Decimal("0")

    for aid in returning_ids:
        rrow = recent_rows[aid]
        prow = prior_rows[aid]
        recent_vol: Decimal = rrow.cases_9l
        prior_vol: Decimal = prow.cases_9l
        diff = recent_vol - prior_vol
        if diff == 0:
            continue
        entry = {
            "account_id": aid,
            "name": rrow.name,
            "state_code": rrow.state_code,
            "city": rrow.city,
            "distributor_name": rrow.distributor_code,
            "recent_9l": recent_vol,
            "prior_9l": prior_vol,
            "diff_9l": diff,
        }
        if diff > 0:
            growing.append(entry)
            growing_total += diff
        else:
            declining.append(entry)
            declining_total += -diff

    growing.sort(key=lambda a: cast(Decimal, a["diff_9l"]), reverse=True)
    declining.sort(key=lambda a: cast(Decimal, a["diff_9l"]))

    return {
        "reference_date": ref,
        "window_months": window_months,
        "recent_window_start": recent_from,
        "prior_window_start": prior_from,
        "prior_window_end": prior_to,
        "growing_accounts": growing,
        "declining_accounts": declining,
        "growing_count": len(growing),
        "declining_count": len(declining),
        "growing_volume": growing_total,
        "declining_volume": declining_total,
    }


# ----------------------------------------------------------------
# Velocity Analysis
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
    latest: date | None = await session.scalar(select(func.max(DepFact.period_month)))
    ref: date = latest or date.today()
    recent_cutoff = ref - timedelta(days=recent_window_months * 31)
    prior_cutoff = recent_cutoff - timedelta(days=recent_window_months * 31)

    stmt = (
        select(
            DepAccount.id.label("account_id"),
            DepAccount.name.label("name"),
            DepAccount.state_code.label("state_code"),
            DepAccount.city.label("city"),
            DepAccount.distributor_code.label("distributor_code"),
            DepFact.period_month.label("period_month"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(
            DepAccount.id,
            DepAccount.name,
            DepAccount.state_code,
            DepAccount.city,
            DepAccount.distributor_code,
            DepFact.period_month,
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
                "distributor_name": row.distributor_code,
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


# ----------------------------------------------------------------
# Product Performance — strategic per-SKU view
# ----------------------------------------------------------------


def _classify_product_momentum(velocity_pct: float | None) -> str:
    """Bucket a SKU's QoQ % into a momentum tier the UI can badge.

    ``velocity_pct is None`` means there was no prior-3M baseline at
    all — i.e. a freshly launched (or recently restarted) SKU.
    """
    if velocity_pct is None:
        return "new"
    if velocity_pct >= 25:
        return "rising"
    if velocity_pct >= -10:
        return "steady"
    if velocity_pct >= -25:
        return "slipping"
    return "declining"


async def get_product_performance(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Rich per-SKU performance view that powers the Product Performance section.

    Reference month: ``date_to`` if provided, else the latest
    ``period_month`` in the data. Sparkline + momentum windows are
    anchored to it. Date range filter is applied to *all* aggregates
    (volume, accounts, states, top state, top account) but not to the
    sparkline series — the sparkline always spans the 12 months ending
    at the reference, so trajectory stays comparable across SKUs.
    """
    latest: date | None = await session.scalar(select(func.max(DepFact.period_month)))
    ref: date = date_to or latest or date.today()
    ref_month_start = date(ref.year, ref.month, 1)

    # Sparkline month axis — 12 cells ending at ``ref``, ascending.
    month_axis: list[date] = []
    y, m = ref_month_start.year, ref_month_start.month
    for i in range(11, -1, -1):
        nm = m - i
        ny = y
        while nm <= 0:
            nm += 12
            ny -= 1
        month_axis.append(date(ny, nm, 1))

    # YoY axis — 24 cells ending at ``ref``. ``month_axis`` is the
    # tail 12; the head 12 are the prior year used for the YoY
    # comparison only. We fetch the series query over the 24-month
    # range to compute both windows from one pass.
    month_axis_24: list[date] = []
    for i in range(23, -1, -1):
        nm = m - i
        ny = y
        while nm <= 0:
            nm += 12
            ny -= 1
        month_axis_24.append(date(ny, nm, 1))
    earliest_month = month_axis_24[0]
    recent_window_start = month_axis[-3]  # first month of last 3M
    prior_window_start = month_axis[-6]  # first month of prior 3M

    # Date-range filter clauses applied to per-product aggregates (NOT
    # to the 12-month sparkline query, which always uses month_axis).
    range_clauses: list[Any] = []
    if date_from is not None:
        range_clauses.append(DepFact.period_month >= date_from)
    if date_to is not None:
        range_clauses.append(DepFact.period_month <= date_to)

    # Pass 1 — per-product aggregates: volume, account/state counts,
    # first/last active month. Only non-zero cells contribute to the
    # first/last active bounds so a row of zeros doesn't make a dead
    # SKU look alive.
    agg_stmt = (
        select(
            DepProduct.id.label("product_id"),
            DepProduct.full_name.label("product_name"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
            func.coalesce(func.sum(DepFact.cases_physical), 0).label("cases_physical"),
            func.count(distinct(DepFact.account_id)).label("account_count"),
            func.count(distinct(DepAccount.state_code)).label("state_count"),
            # period_month returned only for rows with non-zero
            # volume — min/max ignore the NULLs so a row of zeros
            # doesn't make a dead SKU look alive.
            func.min(case((DepFact.cases_9l != 0, DepFact.period_month))).label("first_active"),
            func.max(case((DepFact.cases_9l != 0, DepFact.period_month))).label("last_active"),
        )
        .select_from(DepFact)
        .join(DepProduct, DepProduct.id == DepFact.product_id)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(DepProduct.id, DepProduct.full_name)
        .order_by(func.sum(DepFact.cases_9l).desc())
    )
    for clause in range_clauses:
        agg_stmt = agg_stmt.where(clause)
    agg_rows = (await session.execute(agg_stmt)).all()

    # Pass 2 — top 3 STATES per product within range. ROW_NUMBER over
    # (product_id, ordered by state volume desc) gives a ranking; we
    # take rn <= 3. account_count per (product, state) lets the UI
    # surface "FL · 27% · 612 accounts".
    state_subq = (
        select(
            DepFact.product_id.label("product_id"),
            DepAccount.state_code.label("state_code"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("state_9l"),
            func.count(distinct(DepFact.account_id)).label("state_account_count"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(DepFact.product_id, DepAccount.state_code)
    )
    for clause in range_clauses:
        state_subq = state_subq.where(clause)
    state_subq_cte = state_subq.subquery()
    state_rank = (
        select(
            state_subq_cte.c.product_id,
            state_subq_cte.c.state_code,
            state_subq_cte.c.state_9l,
            state_subq_cte.c.state_account_count,
            func.row_number()
            .over(
                partition_by=state_subq_cte.c.product_id,
                order_by=state_subq_cte.c.state_9l.desc().nulls_last(),
            )
            .label("rn"),
        )
        .select_from(state_subq_cte)
        .subquery()
    )
    top_state_rows = (
        await session.execute(
            select(
                state_rank.c.product_id,
                state_rank.c.state_code,
                state_rank.c.state_9l,
                state_rank.c.state_account_count,
                state_rank.c.rn,
            ).where(state_rank.c.rn <= 3)
        )
    ).all()
    top_states_by_product: dict[int, list[dict[str, Any]]] = {}
    for r in top_state_rows:
        top_states_by_product.setdefault(r.product_id, []).append(
            {
                "state_code": r.state_code,
                "cases_9l": r.state_9l,
                "account_count": r.state_account_count,
            }
        )

    # Pass 3 — top 3 ACCOUNTS per product within range, same shape.
    # state_code travels with the account so the deep-dive UI shows
    # "Total Wine #842 · FL · 18% of SKU" without an extra join.
    acct_subq = (
        select(
            DepFact.product_id.label("product_id"),
            DepFact.account_id.label("account_id"),
            DepAccount.name.label("account_name"),
            DepAccount.state_code.label("state_code"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("account_9l"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(
            DepFact.product_id,
            DepFact.account_id,
            DepAccount.name,
            DepAccount.state_code,
        )
    )
    for clause in range_clauses:
        acct_subq = acct_subq.where(clause)
    acct_subq_cte = acct_subq.subquery()
    acct_rank = (
        select(
            acct_subq_cte.c.product_id,
            acct_subq_cte.c.account_id,
            acct_subq_cte.c.account_name,
            acct_subq_cte.c.state_code,
            acct_subq_cte.c.account_9l,
            func.row_number()
            .over(
                partition_by=acct_subq_cte.c.product_id,
                order_by=acct_subq_cte.c.account_9l.desc().nulls_last(),
            )
            .label("rn"),
        )
        .select_from(acct_subq_cte)
        .subquery()
    )
    top_acct_rows = (
        await session.execute(
            select(
                acct_rank.c.product_id,
                acct_rank.c.account_id,
                acct_rank.c.account_name,
                acct_rank.c.state_code,
                acct_rank.c.account_9l,
                acct_rank.c.rn,
            ).where(acct_rank.c.rn <= 3)
        )
    ).all()
    top_accounts_by_product: dict[int, list[dict[str, Any]]] = {}
    for r in top_acct_rows:
        top_accounts_by_product.setdefault(r.product_id, []).append(
            {
                "account_id": r.account_id,
                "name": r.account_name,
                "state_code": r.state_code,
                "cases_9l": r.account_9l,
            }
        )

    # Pass 4 — 24-month per-product monthly volume series. The tail 12
    # cells are the sparkline; the head 12 form the prior-year window
    # used for YoY. Spans ``month_axis_24`` regardless of the requested
    # range so trajectory + YoY stay comparable across SKUs.
    series_stmt = (
        select(
            DepFact.product_id.label("product_id"),
            DepFact.period_month.label("period_month"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("cases_9l"),
        )
        .select_from(DepFact)
        .where(DepFact.period_month >= earliest_month)
        .where(DepFact.period_month <= ref_month_start)
        .group_by(DepFact.product_id, DepFact.period_month)
    )
    series_by_product: dict[int, dict[date, Decimal]] = {}
    for srow in (await session.execute(series_stmt)).all():
        series_by_product.setdefault(srow.product_id, {})[srow.period_month] = srow.cases_9l

    # Pass 5 — top 3 DISTRIBUTORS per product within range. Distributor
    # identity is the raw iDIG ``distributor_code`` (e.g. "FL13") since
    # we don't have a canonical distributor entity for depletions yet.
    dist_subq = (
        select(
            DepFact.product_id.label("product_id"),
            DepAccount.distributor_code.label("distributor_code"),
            func.coalesce(func.sum(DepFact.cases_9l), 0).label("dist_9l"),
            func.count(distinct(DepFact.account_id)).label("dist_account_count"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(DepFact.product_id, DepAccount.distributor_code)
    )
    for clause in range_clauses:
        dist_subq = dist_subq.where(clause)
    dist_subq_cte = dist_subq.subquery()
    dist_rank = (
        select(
            dist_subq_cte.c.product_id,
            dist_subq_cte.c.distributor_code,
            dist_subq_cte.c.dist_9l,
            dist_subq_cte.c.dist_account_count,
            func.row_number()
            .over(
                partition_by=dist_subq_cte.c.product_id,
                order_by=dist_subq_cte.c.dist_9l.desc().nulls_last(),
            )
            .label("rn"),
        )
        .select_from(dist_subq_cte)
        .subquery()
    )
    top_dist_rows = (
        await session.execute(
            select(
                dist_rank.c.product_id,
                dist_rank.c.distributor_code,
                dist_rank.c.dist_9l,
                dist_rank.c.dist_account_count,
                dist_rank.c.rn,
            ).where(dist_rank.c.rn <= 3)
        )
    ).all()
    top_distributors_by_product: dict[int, list[dict[str, Any]]] = {}
    for r in top_dist_rows:
        top_distributors_by_product.setdefault(r.product_id, []).append(
            {
                "distributor_code": r.distributor_code,
                "cases_9l": r.dist_9l,
                "account_count": r.dist_account_count,
            }
        )
    # Distinct distributor count per product (so the UI can say
    # "concentrated in 1 of 4 distributors").
    dist_count_stmt = (
        select(
            DepFact.product_id.label("product_id"),
            func.count(distinct(DepAccount.distributor_code)).label("dist_count"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .group_by(DepFact.product_id)
    )
    for clause in range_clauses:
        dist_count_stmt = dist_count_stmt.where(clause)
    dist_count_by_product: dict[int, int] = {
        r.product_id: r.dist_count for r in (await session.execute(dist_count_stmt)).all()
    }

    # Pass 6 — per-(product, account) lifecycle for momentum metrics.
    # We need each account's first and last non-zero month for this
    # SKU, then bucket in Python: active in last 3M, gained in last 3M
    # (first_active is inside the recent window), churned (last_active
    # is inside the prior 3M but NOT inside the recent 3M).
    lifecycle_stmt = select(
        DepFact.product_id.label("product_id"),
        DepFact.account_id.label("account_id"),
        func.min(case((DepFact.cases_9l != 0, DepFact.period_month))).label("first_active"),
        func.max(case((DepFact.cases_9l != 0, DepFact.period_month))).label("last_active"),
    ).group_by(DepFact.product_id, DepFact.account_id)
    for clause in range_clauses:
        lifecycle_stmt = lifecycle_stmt.where(clause)
    lifecycle_rows = (await session.execute(lifecycle_stmt)).all()
    # Per-product counters initialised as we walk lifecycle rows.
    momentum_by_product: dict[int, dict[str, int]] = {}
    for lc in lifecycle_rows:
        if lc.last_active is None:
            continue  # never had a non-zero month — skip
        slot = momentum_by_product.setdefault(
            lc.product_id, {"active_90d": 0, "gained_90d": 0, "churned_90d": 0}
        )
        active_recent = lc.last_active >= recent_window_start
        if active_recent:
            slot["active_90d"] += 1
            if lc.first_active is not None and lc.first_active >= recent_window_start:
                slot["gained_90d"] += 1
        elif lc.last_active >= prior_window_start and lc.last_active < recent_window_start:
            slot["churned_90d"] += 1

    # Pass 7 — states with any non-zero activity in the recent 3-month
    # window (a footprint check that complements ``state_count``).
    states_recent_stmt = (
        select(
            DepFact.product_id.label("product_id"),
            func.count(distinct(DepAccount.state_code)).label("states_recent_q"),
        )
        .select_from(DepFact)
        .join(DepAccount, DepAccount.id == DepFact.account_id)
        .where(DepFact.period_month >= recent_window_start)
        .where(DepFact.period_month <= ref_month_start)
        .where(DepFact.cases_9l != 0)
        .group_by(DepFact.product_id)
    )
    for clause in range_clauses:
        states_recent_stmt = states_recent_stmt.where(clause)
    states_recent_by_product: dict[int, int] = {
        r.product_id: r.states_recent_q for r in (await session.execute(states_recent_stmt)).all()
    }

    # Assemble the per-SKU records.
    items: list[dict[str, Any]] = []
    total_9l: Decimal = sum((row.cases_9l for row in agg_rows), Decimal("0"))
    for row in agg_rows:
        series_dict = series_by_product.get(row.product_id, {})
        # 24-month values; tail 12 = sparkline; head 12 = prior year.
        series_values_24: list[Decimal] = [series_dict.get(m, Decimal("0")) for m in month_axis_24]
        series_values: list[Decimal] = series_values_24[-12:]
        recent_3m = sum(series_values[-3:], Decimal("0"))
        prior_3m = sum(series_values[-6:-3], Decimal("0"))
        velocity_pct: float | None = None
        if prior_3m > 0:
            velocity_pct = float((recent_3m - prior_3m) / prior_3m * 100)
        # YoY — last 12 months vs the 12 before that.
        recent_12m = sum(series_values_24[-12:], Decimal("0"))
        prior_12m = sum(series_values_24[:12], Decimal("0"))
        yoy_pct: float | None = None
        if prior_12m > 0:
            yoy_pct = float((recent_12m - prior_12m) / prior_12m * 100)

        cases_9l: Decimal = row.cases_9l
        accounts: int = row.account_count
        avg_per_account = cases_9l / accounts if accounts > 0 else Decimal("0")
        share = float(cases_9l / total_9l) if total_9l > 0 else 0.0

        # Build top-3 state list with per-row share. The legacy
        # ``top_state`` / ``top_state_share`` fields are derived from
        # the first entry so the existing UI keeps working unchanged.
        raw_states = top_states_by_product.get(row.product_id, [])
        top_states: list[dict[str, Any]] = [
            {
                "state_code": s["state_code"],
                "cases_9l": s["cases_9l"],
                "share": (
                    float(cast(Decimal, s["cases_9l"]) / cases_9l)
                    if cases_9l > 0 and s["cases_9l"] > 0
                    else 0.0
                ),
                "account_count": s["account_count"],
            }
            for s in raw_states
        ]
        if top_states:
            top_state = top_states[0]["state_code"]
            top_state_share = top_states[0]["share"]
        else:
            top_state = None
            top_state_share = 0.0

        # Same shape for top-3 accounts. Legacy fields derived from
        # the first entry.
        raw_accts = top_accounts_by_product.get(row.product_id, [])
        top_accounts: list[dict[str, Any]] = [
            {
                "account_id": a["account_id"],
                "name": a["name"],
                "state_code": a["state_code"],
                "cases_9l": a["cases_9l"],
                "share": (
                    float(cast(Decimal, a["cases_9l"]) / cases_9l)
                    if cases_9l > 0 and a["cases_9l"] > 0
                    else 0.0
                ),
            }
            for a in raw_accts
        ]
        if top_accounts:
            top_acct_id = top_accounts[0]["account_id"]
            top_acct_name = top_accounts[0]["name"]
            top_acct_share = top_accounts[0]["share"]
        else:
            top_acct_id = None
            top_acct_name = None
            top_acct_share = 0.0

        # Build top-3 distributor list with per-row share. Legacy
        # ``top_distributor_*`` fields derived from the first entry.
        raw_dists = top_distributors_by_product.get(row.product_id, [])
        top_distributors: list[dict[str, Any]] = [
            {
                "distributor_code": d["distributor_code"],
                "cases_9l": d["cases_9l"],
                "share": (
                    float(cast(Decimal, d["cases_9l"]) / cases_9l)
                    if cases_9l > 0 and d["cases_9l"] > 0
                    else 0.0
                ),
                "account_count": d["account_count"],
            }
            for d in raw_dists
        ]
        if top_distributors:
            top_dist_code = top_distributors[0]["distributor_code"]
            top_dist_share = top_distributors[0]["share"]
        else:
            top_dist_code = None
            top_dist_share = 0.0
        distributor_count = dist_count_by_product.get(row.product_id, 0)

        # Account momentum — pulled from the lifecycle bucketing.
        momentum_counts = momentum_by_product.get(
            row.product_id, {"active_90d": 0, "gained_90d": 0, "churned_90d": 0}
        )

        # States active in the recent 3-month window.
        states_active_recent = states_recent_by_product.get(row.product_id, 0)

        # Months-active in the 12-month sparkline window.
        months_active_12m = sum(1 for v in series_values if v > 0)

        # Peak month inside the 12-month window.
        peak_month: date | None = None
        peak_month_9l = Decimal("0")
        for m_date, v in zip(month_axis, series_values, strict=True):
            if v > peak_month_9l:
                peak_month_9l = v
                peak_month = m_date

        items.append(
            {
                "product_id": row.product_id,
                "product_name": row.product_name,
                "cases_9l": cases_9l,
                "cases_physical": row.cases_physical,
                "pct_of_9l": share,
                "account_count": accounts,
                "state_count": row.state_count,
                "avg_9l_per_account": avg_per_account,
                "top_account_id": top_acct_id,
                "top_account_name": top_acct_name,
                "top_account_share": top_acct_share,
                "top_state": top_state,
                "top_state_share": top_state_share,
                "recent_3m_9l": recent_3m,
                "prior_3m_9l": prior_3m,
                "velocity_pct": velocity_pct,
                "momentum": _classify_product_momentum(velocity_pct),
                "first_active": row.first_active,
                "last_active": row.last_active,
                "monthly_series": [
                    {"period": m, "cases_9l": v}
                    for m, v in zip(month_axis, series_values, strict=True)
                ],
                "top_accounts": top_accounts,
                "top_states": top_states,
                # ---- round-2 strategic fields ----
                "recent_12m_9l": recent_12m,
                "prior_12m_9l": prior_12m,
                "yoy_pct": yoy_pct,
                "top_distributor_code": top_dist_code,
                "top_distributor_share": top_dist_share,
                "distributor_count": distributor_count,
                "top_distributors": top_distributors,
                "accounts_active_90d": momentum_counts["active_90d"],
                "accounts_gained_90d": momentum_counts["gained_90d"],
                "accounts_churned_90d": momentum_counts["churned_90d"],
                "states_active_recent_q": states_active_recent,
                "months_active_12m": months_active_12m,
                "peak_month": peak_month,
                "peak_month_9l": peak_month_9l,
            }
        )

    # Top-3 concentration — share of the 3 biggest SKUs.
    top_3_share = 0.0
    if total_9l > 0:
        top_3_sum: Decimal = sum(
            (cast(Decimal, item["cases_9l"]) for item in items[:3]), Decimal("0")
        )
        top_3_share = float(top_3_sum / total_9l)

    return {
        "reference_date": ref,
        "products": items,
        "total_9l": total_9l,
        "top_3_share": top_3_share,
    }
