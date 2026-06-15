"""Pydantic response models for the depletions API."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DepletionsKPIs(BaseModel):
    """Top-line depletions numbers for a date range."""

    model_config = ConfigDict(frozen=True)

    total_9l: Decimal = Field(description="Sum of cases_9l across the period")
    total_physical: Decimal = Field(description="Sum of cases_physical (0 when source omits it)")
    unique_accounts: int
    unique_products: int
    unique_states: int
    unique_distributors: int
    period_start: date | None
    period_end: date | None
    avg_9l_per_account: Decimal | None


class DepletionsTrendPoint(BaseModel):
    """One monthly bucket of depletion volume."""

    model_config = ConfigDict(frozen=True)

    period: date
    cases_9l: Decimal
    cases_physical: Decimal
    active_accounts: int


class DepletionsTrendResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    grain: str
    points: list[DepletionsTrendPoint]


class DepletionsProductPerformance(BaseModel):
    """One product's depletion contribution."""

    model_config = ConfigDict(frozen=True)

    product_id: int
    product_name: str
    cases_9l: Decimal
    cases_physical: Decimal
    account_count: int
    state_count: int
    pct_of_9l: float


class DepletionsProductResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    products: list[DepletionsProductPerformance]
    total_9l: Decimal


class DepletionsStatePerformance(BaseModel):
    """One state's depletion contribution."""

    model_config = ConfigDict(frozen=True)

    state_code: str | None
    cases_9l: Decimal
    cases_physical: Decimal
    account_count: int
    pct_of_9l: float


class DepletionsStateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    states: list[DepletionsStatePerformance]
    total_9l: Decimal


class TopAccount(BaseModel):
    """A single account's depletion summary for the leaderboard."""

    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    state_code: str | None
    city: str | None
    distributor_name: str | None
    # Broker's premises classification: 'ON' / 'OFF' / 'NA' / None.
    # See FollowUpAccount.premises_type for full semantics.
    premises_type: str | None
    cases_9l: Decimal
    cases_physical: Decimal
    product_count: int
    last_active_period: date | None
    pct_of_9l: float


class TopAccountsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    accounts: list[TopAccount]
    total_9l: Decimal


# ----------------------------------------------------------------
# Account x Month heatmap
# ----------------------------------------------------------------


class AccountMonthlyProductBreakdown(BaseModel):
    """One product line inside a (account, month) cell.

    Surfaced so the heatmap's cell-hover tooltip can answer "what
    did they actually order that month?" beyond just the total 9L.
    Sorted by ``cases_9l`` desc when emitted by the service.
    """

    model_config = ConfigDict(frozen=True)

    product_id: int
    product_name: str
    cases_9l: Decimal


class AccountMonthlyVolume(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: date
    cases_9l: Decimal
    # Per-month product mix for this account. Empty list when the
    # account didn't move any product that month.
    products: list[AccountMonthlyProductBreakdown]


class AccountMonthlyGridRow(BaseModel):
    """One row of the heatmap: an account plus its full monthly volume series."""

    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    # Full mailing-address fields surfaced so the heatmap's account
    # label tooltip can show the rep where to call / visit.
    address: str | None
    state_code: str | None
    city: str | None
    county: str | None
    zip_code: str | None
    distributor_code: str | None
    # Broker premises classification ('ON' / 'OFF' / 'NA' / None) so
    # the heatmap row can render the channel badge next to the name.
    premises_type: str | None
    total_9l: Decimal
    months_active: int
    frequency: str
    monthly_volumes: list[AccountMonthlyVolume]


class AccountMonthlyGridResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    period_start: date | None
    period_end: date | None
    months: list[date]
    accounts: list[AccountMonthlyGridRow]
