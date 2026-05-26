"""Pydantic response models for the strategic / analytical endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

# ----------------------------------------------------------------
# White-Space Matrix
# ----------------------------------------------------------------


class WhiteSpaceProduct(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    revenue: Decimal


class WhiteSpaceState(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    revenue: Decimal


class WhiteSpaceCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    state_code: str
    revenue: Decimal
    cases: Decimal


class WhiteSpaceMatrixResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    products: list[WhiteSpaceProduct]
    states: list[WhiteSpaceState]
    cells: list[WhiteSpaceCell]
    total_combos: int
    filled_combos: int
    gap_count: int
    gap_pct: float


# ----------------------------------------------------------------
# Order Analysis
# ----------------------------------------------------------------


class OrderSizeBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    min: float
    max: float | None
    count: int
    revenue: Decimal


class ProductPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_a_id: int
    product_a_name: str
    product_b_id: int
    product_b_name: str
    count: int


class DistributorOrderFrequency(BaseModel):
    model_config = ConfigDict(frozen=True)

    distributor_id: int | None
    distributor_name: str | None
    order_count: int
    total_revenue: Decimal
    avg_order_value: Decimal


class MonthlyOrderPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: date
    orders: int
    revenue: Decimal
    avg_value: Decimal


class OrderAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_orders: int
    total_revenue: Decimal
    avg_order_value: Decimal
    median_order_value: Decimal
    size_buckets: list[OrderSizeBucket]
    multi_product_orders: int
    single_product_orders: int
    avg_multi_value: Decimal
    avg_single_value: Decimal
    top_product_pairs: list[ProductPair]
    distributor_frequency: list[DistributorOrderFrequency]
    repeat_buyers: int
    one_time_buyers: int
    monthly_orders: list[MonthlyOrderPoint]


# ----------------------------------------------------------------
# Risk / Concentration
# ----------------------------------------------------------------


class ConcentrationMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    top_1_share: float
    top_3_share: float
    top_5_share: float
    hhi: float
    entry_count: int


class RiskDashboardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_concentration: ConcentrationMetric
    distributor_concentration: ConcentrationMetric
    state_concentration: ConcentrationMetric


# ----------------------------------------------------------------
# Velocity Analysis (depletions)
# ----------------------------------------------------------------


class VelocityAccount(BaseModel):
    """Per-account depletion velocity over the available history."""

    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    state_code: str | None
    city: str | None
    distributor_name: str | None
    months_active: int
    total_9l: Decimal
    avg_9l_per_month: Decimal
    recent_3m_avg: Decimal
    prior_3m_avg: Decimal
    velocity_change_pct: float | None
    category: str


class VelocityCategoryStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str
    count: int
    total_9l: Decimal


class VelocityAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    accounts: list[VelocityAccount]
    category_stats: list[VelocityCategoryStats]


# ----------------------------------------------------------------
# Follow-Up Tracker (depletions)
# ----------------------------------------------------------------


class FollowUpAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    state_code: str | None
    city: str | None
    distributor_name: str | None
    last_active: date
    days_since: int
    total_9l: Decimal
    product_count: int


class FollowUpBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    count: int
    total_9l: Decimal
    accounts: list[FollowUpAccount]


class FollowUpTrackerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    buckets: list[FollowUpBucket]


# ----------------------------------------------------------------
# New vs Lost Accounts (depletions)
# ----------------------------------------------------------------


class AccountBrief(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    state_code: str | None
    city: str | None
    distributor_name: str | None
    cases_9l: Decimal


class NewVsLostAccountsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    window_months: int
    recent_window_start: date
    prior_window_start: date
    prior_window_end: date
    new_count: int
    lost_count: int
    new_total_9l: Decimal
    lost_total_9l: Decimal
    new_accounts: list[AccountBrief]
    lost_accounts: list[AccountBrief]
