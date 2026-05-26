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
    cases_9l: Decimal
    cases_physical: Decimal
    product_count: int
    last_active_period: date | None
    pct_of_9l: float


class TopAccountsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    accounts: list[TopAccount]
    total_9l: Decimal
