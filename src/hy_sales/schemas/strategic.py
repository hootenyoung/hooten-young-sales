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


class FollowUpMonthlyVolume(BaseModel):
    """One bar in the per-account 12-month sparkline."""

    model_config = ConfigDict(frozen=True)

    period: date
    cases_9l: Decimal


class FollowUpAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    address: str | None
    state_code: str | None
    city: str | None
    county: str | None
    zip_code: str | None
    distributor_name: str | None
    last_active: date
    last_active_label: str
    days_since: int
    total_9l: Decimal
    product_count: int
    # Short product names (brand prefix stripped) sorted by per-product
    # volume descending. UI surfaces the first few as chips with a
    # "+N more" badge for the rest.
    products: list[str]

    # Customer-since — first month the account ever had a non-zero
    # depletion. Surfaces "long-time loyal account" vs "new account"
    # in the UI.
    customer_since: date | None
    customer_since_label: str | None

    # Velocity — recent 3 months vs prior 3 months, computed on the
    # backend so the UI can render a single chip without re-deriving.
    # ``velocity_pct`` is null when prior_3m is zero (no baseline to
    # compare against). UI shows "New activity" in that case.
    recent_3m_9l: Decimal
    prior_3m_9l: Decimal
    velocity_pct: float | None

    # Premises classification from the broker (iDIG OnOff Premises):
    #   'ON'  — on-premises (bars, restaurants)
    #   'OFF' — off-premises (liquor stores, retail)
    #   'NA'  — broker actively classified as not-applicable
    #   None  — we don't have this info yet (older accounts that
    #           predate the column or haven't appeared in a
    #           premises-aware file)
    premises_type: str | None

    # 12-month per-month volume series ending at the reference month.
    # The UI renders this as a small inline bar sparkline so a rep can
    # eyeball the order pattern without reading any numbers.
    monthly_series: list[FollowUpMonthlyVolume]


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
    premises_type: str | None
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


# ----------------------------------------------------------------
# Account Growth & Decline (returning accounts comparison)
# ----------------------------------------------------------------


class GrowthDeclineAccount(BaseModel):
    """One returning account with its recent vs prior period totals."""

    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    state_code: str | None
    city: str | None
    distributor_name: str | None
    # Broker's premises classification: 'ON' / 'OFF' / 'NA' / None.
    premises_type: str | None
    recent_9l: Decimal
    prior_9l: Decimal
    diff_9l: Decimal


class GrowthDeclineResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    window_months: int
    recent_window_start: date
    prior_window_start: date
    prior_window_end: date
    growing_count: int
    declining_count: int
    growing_volume: Decimal
    declining_volume: Decimal
    growing_accounts: list[GrowthDeclineAccount]
    declining_accounts: list[GrowthDeclineAccount]


# ----------------------------------------------------------------
# Product Performance (depletions — strategic per-SKU view)
# ----------------------------------------------------------------

# Momentum tier — what the UI surfaces as the per-SKU badge.
#   rising     — recent vs prior > +25%
#   steady     — between -10% and +25%
#   slipping   — between -25% and -10%
#   declining  — below -25%
#   new        — no prior-3M activity at all (debut SKU or restart)
ProductMomentum = str  # 'rising' | 'steady' | 'slipping' | 'declining' | 'new'


class ProductMonthlyVolume(BaseModel):
    """One bar in the per-product 12-month sparkline."""

    model_config = ConfigDict(frozen=True)

    period: date
    cases_9l: Decimal


class ProductTopAccount(BaseModel):
    """One row in the per-SKU top-accounts list (max 3)."""

    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    state_code: str | None
    premises_type: str | None
    cases_9l: Decimal
    share: float  # 0..1 of this SKU's total


class ProductTopState(BaseModel):
    """One row in the per-SKU top-states list (max 3)."""

    model_config = ConfigDict(frozen=True)

    state_code: str | None
    cases_9l: Decimal
    share: float  # 0..1 of this SKU's total
    account_count: int


class ProductTopDistributor(BaseModel):
    """One row in the per-SKU top-distributors list (max 3)."""

    model_config = ConfigDict(frozen=True)

    # iDIG short code (e.g. "FL13") — we don't have a canonical
    # distributor entity for depletions yet, so the code stands in as
    # the identifier. See ``depletions_strategic`` module docstring.
    distributor_code: str | None
    cases_9l: Decimal
    share: float  # 0..1 of this SKU's total
    account_count: int


class ProductPerformanceItem(BaseModel):
    """A single SKU's strategic depletion summary.

    All metrics are computed across the requested date range. When the
    range spans fewer than 6 months, recent/prior 3M may overlap with
    the dataset edges — ``velocity_pct`` is null in those edge cases
    so the UI can render a "New" badge instead of a misleading number.
    """

    model_config = ConfigDict(frozen=True)

    product_id: int
    product_name: str

    # Headline volume + share
    cases_9l: Decimal
    cases_physical: Decimal
    pct_of_9l: float

    # Distribution shape
    account_count: int
    state_count: int
    # Depth metric — surfaces "hero" SKUs (high volume per account) vs
    # "wide" SKUs (low per-account, sold everywhere).
    avg_9l_per_account: Decimal

    # Concentration risk — % of this SKU's volume from its top account
    # and top state. UI flags concentration > 30%.
    top_account_id: int | None
    top_account_name: str | None
    top_account_share: float  # 0..1
    top_state: str | None
    top_state_share: float  # 0..1

    # Momentum window — recent 3M ending at the reference month vs the
    # 3M before that. ``velocity_pct`` is null when prior_3m is zero.
    recent_3m_9l: Decimal
    prior_3m_9l: Decimal
    velocity_pct: float | None
    momentum: ProductMomentum

    # Lifecycle — first/last month with non-zero depletion (within the
    # requested range). Used to render "Since Mar '24" labels and to
    # spot SKUs that have gone dark.
    first_active: date | None
    last_active: date | None

    # 12-month per-month volume series ending at the reference month.
    # Drives the inline row sparkline.
    monthly_series: list[ProductMonthlyVolume]

    # Top 3 accounts and top 3 states by 9L within the range. Drives
    # the expandable per-SKU deep-dive (account list, state list) and
    # the richer hover tooltips on Reach / Top State.
    top_accounts: list[ProductTopAccount]
    top_states: list[ProductTopState]

    # ---- Strategic enrichments (round 2) ----

    # Year-over-year — recent 12 months vs the 12 months before that,
    # anchored at the reference month. Smooths the noise that makes
    # short windows always look "declining" near seasonal lows.
    # ``yoy_pct`` is null when prior_12m_9l is zero.
    recent_12m_9l: Decimal
    prior_12m_9l: Decimal
    yoy_pct: float | None

    # Distributor concentration — same shape as account / state risk.
    # A high top_distributor_share is more strategic: losing one
    # wholesaler relationship is harder to recover from than losing
    # one outlet.
    top_distributor_code: str | None
    top_distributor_share: float  # 0..1
    distributor_count: int
    top_distributors: list[ProductTopDistributor]

    # Account momentum (last 3 months vs the 3 months before that):
    #   active_90d  — accounts with non-zero activity in the last 3M
    #   gained_90d  — accounts whose first non-zero month for this SKU
    #                 falls inside the recent 3M window
    #   churned_90d — accounts active in prior 3M but silent in last 3M
    # ``net_90d`` = gained - churned is computed client-side; we ship
    # the raw inputs so the UI can show both directions.
    accounts_active_90d: int
    accounts_gained_90d: int
    accounts_churned_90d: int

    # Distribution footprint — states with any non-zero activity in
    # the last 3 months. ``states_active_recent_q`` vs ``state_count``
    # surfaces SKUs losing distribution before volume reflects it.
    states_active_recent_q: int

    # Activity rhythm — count of months in the 12-month sparkline
    # window with non-zero volume. 12/12 = always on, 4/12 = sporadic.
    months_active_12m: int

    # Peak month inside the 12-month window — used for "Peaks in Dec"
    # seasonality labels in the UI.
    peak_month: date | None
    peak_month_9l: Decimal


class ProductPerformanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    products: list[ProductPerformanceItem]
    total_9l: Decimal
    # Portfolio concentration — share of the top-3 SKUs by 9L. UI flags
    # > 0.7 as "narrow portfolio".
    top_3_share: float


# ----------------------------------------------------------------
# State Performance (depletions — strategic per-state view)
# ----------------------------------------------------------------

# Re-used momentum tier alias for state-level signals.
StateMomentum = str  # 'rising' | 'steady' | 'slipping' | 'declining' | 'new'


class StateMonthlyVolume(BaseModel):
    """One bar in the per-state 12-month sparkline."""

    model_config = ConfigDict(frozen=True)

    period: date
    cases_9l: Decimal


class StateYearlyVolume(BaseModel):
    """One bar in the per-state yearly comparison.

    ``is_ytd`` is True for the calendar year that contains the
    reference month — the value is year-to-date rather than a full
    twelve months, and the UI marks the bar accordingly so the
    comparison isn't read as apples-to-apples.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    cases_9l: Decimal
    is_ytd: bool
    # Count of distinct months included. For YTD years the UI shows
    # "Jan-Jun 2026" using this count.
    months_covered: int


class StateTopProduct(BaseModel):
    """One row in the per-state top-products list (max 3)."""

    model_config = ConfigDict(frozen=True)

    product_id: int
    product_name: str
    cases_9l: Decimal
    share: float  # 0..1 of this state's total


class StateTopAccount(BaseModel):
    """One row in the per-state top-accounts list (max 3)."""

    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    city: str | None
    premises_type: str | None
    cases_9l: Decimal
    share: float  # 0..1 of this state's total


class StateTopDistributor(BaseModel):
    """One row in the per-state top-distributors list (max 3)."""

    model_config = ConfigDict(frozen=True)

    distributor_code: str | None
    cases_9l: Decimal
    share: float  # 0..1 of this state's total
    account_count: int


class PremisesCounts(BaseModel):
    """Account counts by premises classification within a state.

    `unknown` covers accounts whose `premises_type` is NULL in the
    DB (older accounts that predate the broker carrying the column).
    Distinct from `na`, which is an active broker classification.
    """

    model_config = ConfigDict(frozen=True)

    on: int
    off: int
    na: int
    unknown: int


class StatePerformanceItem(BaseModel):
    """A single state's strategic depletion summary.

    Mirrors :class:`ProductPerformanceItem` field-by-field so the UI
    can share components. The "entity" is a state instead of a SKU.
    """

    model_config = ConfigDict(frozen=True)

    state_code: str
    # Headline volume + share
    cases_9l: Decimal
    cases_physical: Decimal
    pct_of_9l: float

    # Distribution shape — accounts in this state, distinct SKUs
    # sold there, and avg 9L per account (depth).
    account_count: int
    product_count: int  # distinct SKUs sold in this state
    avg_9l_per_account: Decimal

    # Top SKU per state — surfaces the mix story ("FL leans on
    # 12 Year Amer at 41% of state volume").
    top_product_id: int | None
    top_product_name: str | None
    top_product_share: float  # 0..1

    # Concentration — top single-account share within the state.
    top_account_id: int | None
    top_account_name: str | None
    top_account_share: float  # 0..1

    # Distributor concentration — losing the wholesaler hurts more
    # than losing one outlet.
    top_distributor_code: str | None
    top_distributor_share: float
    distributor_count: int

    # Top 3 lists for the deep-dive panel.
    top_products: list[StateTopProduct]
    top_accounts: list[StateTopAccount]
    top_distributors: list[StateTopDistributor]

    # Momentum window — recent 3M vs prior 3M (within the requested
    # range, anchored at the reference month).
    recent_3m_9l: Decimal
    prior_3m_9l: Decimal
    velocity_pct: float | None
    momentum: StateMomentum

    # Year-over-year smooths the seasonal noise QoQ catches.
    recent_12m_9l: Decimal
    prior_12m_9l: Decimal
    yoy_pct: float | None

    # Account momentum — accounts gained / churned / active in the
    # last 3M for this state.
    accounts_active_90d: int
    accounts_gained_90d: int
    accounts_churned_90d: int

    # Premises channel mix — number of accounts in this state by the
    # broker's ON/OFF/NA classification. ``unknown`` covers accounts
    # whose premises_type is still NULL in the DB. Sums to
    # ``account_count`` above. See [[hy-premises-semantics]] for the
    # four-state distinction.
    premises_counts: PremisesCounts

    # Lifecycle
    first_active: date | None
    last_active: date | None
    months_active_12m: int

    # Peak month inside the 12-month sparkline window.
    peak_month: date | None
    peak_month_9l: Decimal

    # 12-month monthly series for the row sparkline.
    monthly_series: list[StateMonthlyVolume]

    # Calendar-year aggregates — one entry per year present in the
    # data, oldest first. The latest entry is YTD if it includes the
    # reference month. Drives the top-of-section grouped-bar chart.
    yearly_history: list[StateYearlyVolume]


class StatePerformanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    states: list[StatePerformanceItem]
    total_9l: Decimal
    # Geographic concentration — share of the top-3 states by 9L. UI
    # flags > 0.7 as "narrow footprint".
    top_3_share: float


# ----------------------------------------------------------------
# Account Performance (depletions — strategic per-account view)
# ----------------------------------------------------------------

# Re-used momentum tier — keeps the badge taxonomy consistent across
# entity types (product / state / account).
AccountMomentum = str  # 'rising' | 'steady' | 'slipping' | 'declining' | 'new'


class AccountMonthlyVolume(BaseModel):
    """One bar in the per-account 12-month sparkline."""

    model_config = ConfigDict(frozen=True)

    period: date
    cases_9l: Decimal


class AccountTopProduct(BaseModel):
    """One row in the per-account top-products list (max 3)."""

    model_config = ConfigDict(frozen=True)

    product_id: int
    product_name: str
    cases_9l: Decimal
    share: float  # 0..1 of this account's total


class AccountPerformanceItem(BaseModel):
    """A single account's strategic depletion summary.

    Mirrors the per-SKU / per-state items field-by-field where
    sensible so the dashboard can share visual primitives.
    """

    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str

    # Location / channel — full mailing address surfaced so the UI's
    # location hover tooltip can show the rep where to drive / call.
    address: str | None
    state_code: str | None
    city: str | None
    county: str | None
    zip_code: str | None
    distributor_code: str | None
    # Premises classification — 'ON' / 'OFF' / 'NA' / None (see
    # FollowUpAccount.premises_type for semantics).
    premises_type: str | None

    # Headline volume + share
    cases_9l: Decimal
    cases_physical: Decimal
    pct_of_9l: float  # 0..1 of total portfolio in the requested range

    # Distribution shape — number of distinct SKUs the account buys
    # and avg 9L per active month (depth proxy at the account level).
    product_count: int
    avg_9l_per_active_month: Decimal

    # Top SKU — what the account leans on.
    top_product_id: int | None
    top_product_name: str | None
    top_product_share: float  # 0..1
    top_products: list[AccountTopProduct]

    # Momentum window — recent 3M ending at the reference month vs
    # the 3M before.
    recent_3m_9l: Decimal
    prior_3m_9l: Decimal
    velocity_pct: float | None
    momentum: AccountMomentum

    # Year-over-year (recent 12M vs prior 12M).
    recent_12m_9l: Decimal
    prior_12m_9l: Decimal
    yoy_pct: float | None

    # Lifecycle bounds within the range.
    first_active: date | None
    last_active: date | None
    months_active_12m: int

    # Peak month in the 12-month sparkline window.
    peak_month: date | None
    peak_month_9l: Decimal

    # Days since last non-zero depletion, relative to the reference
    # date. Powers the Dark health flag and the lifecycle facts.
    days_since: int | None

    # 12-month monthly series for the row sparkline.
    monthly_series: list[AccountMonthlyVolume]


class AccountPerformanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    accounts: list[AccountPerformanceItem]
    total_9l: Decimal
    # Concentration — share of the top-10 accounts by 9L. UI flags
    # > 0.5 as "narrow customer base".
    top_10_share: float


# ----------------------------------------------------------------
# Premises Mix
# ----------------------------------------------------------------


class PremisesBucket(BaseModel):
    """One row of the ON / OFF / NA / NULL breakdown.

    ``premises_type`` is the literal column value (None for accounts
    that don't carry the classification yet). ``account_count`` is the
    number of distinct accounts in this bucket; ``total_9l`` is the
    summed lifetime depletions volume for the bucket so the UI can
    weight tiles by 9L as well as by account count.
    """

    model_config = ConfigDict(frozen=True)

    premises_type: str | None
    account_count: int
    total_9l: Decimal
    pct_of_9l: float  # 0..1


class PremisesYearlyBucket(BaseModel):
    """One (premises_type, year) cell of the year-over-year comparison.

    Mirrors :class:`StateYearlyVolume` semantics so the dashboard
    can reuse the same YTD-marking pattern. ``is_ytd`` is True for
    the calendar year that contains the reference month — the value
    is year-to-date rather than a full twelve months. ``months_covered``
    lets the UI render "Jan-Jun 2026" labels for the partial year.
    """

    model_config = ConfigDict(frozen=True)

    premises_type: str | None
    year: int
    cases_9l: Decimal
    is_ytd: bool
    months_covered: int


class PremisesSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    buckets: list[PremisesBucket]
    grand_total_9l: Decimal
    grand_total_accounts: int
    # Year-over-year breakdown per premises_type. One entry per
    # (premises_type, year) cell — the dashboard pivots it into a
    # grouped-bar chart (X = year, bars = ON/OFF/NA/Unknown).
    yearly_history: list[PremisesYearlyBucket]
