"""Pydantic v2 response models for the sales API.

These define the on-the-wire contract between this backend and the
hooten-young-dashboard React UI. Use snake_case throughout — FastAPI
serializes them directly to JSON.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SalesKPIs(BaseModel):
    """Top-line numbers for a date range — powers the dashboard's KPI strip."""

    model_config = ConfigDict(frozen=True)

    total_revenue: Decimal = Field(description="Sum of invoice_lines.amount")
    total_cases: Decimal = Field(description="Sum of invoice_lines.quantity")
    total_commission: Decimal = Field(
        description="total_revenue * commission_rate (from sales.app_config)"
    )
    commission_rate: Decimal = Field(
        description="Commission rate used to derive total_commission",
    )
    total_invoices: int = Field(description="Count of distinct invoices")
    avg_invoice_value: Decimal | None = Field(
        default=None,
        description="total_revenue / total_invoices; null when no invoices",
    )
    unique_customers: int = Field(description="Distinct customers billed")
    unique_products: int = Field(description="Distinct products sold")
    unique_distributors: int = Field(description="Distinct parent distributors")
    unique_states: int = Field(description="Distinct customer states")
    period_start: date | None = Field(
        default=None,
        description="Earliest invoice_date in the result; may be later than the requested 'from'",
    )
    period_end: date | None = Field(
        default=None,
        description="Latest invoice_date in the result",
    )


class SalesTrendPoint(BaseModel):
    """One bucket in a time-series response."""

    model_config = ConfigDict(frozen=True)

    period: date = Field(description="First day of the bucket (e.g. 2026-04-01 for April)")
    revenue: Decimal
    cases: Decimal
    invoices: int


class SalesTrendResponse(BaseModel):
    """Time-series of sales aggregates."""

    model_config = ConfigDict(frozen=True)

    grain: str = Field(description="Bucket size — currently 'month'")
    points: list[SalesTrendPoint]


class ProductPerformance(BaseModel):
    """One product's revenue contribution + distribution detail."""

    model_config = ConfigDict(frozen=True)

    product_id: int
    product_name: str
    revenue: Decimal
    cases: Decimal
    invoice_count: int
    pct_of_revenue: float = Field(description="0..1 share of total revenue in the result")
    avg_price_per_case: Decimal | None = Field(
        default=None,
        description="revenue / cases, or null when no cases sold",
    )
    state_count: int = Field(default=0, description="Count of distinct customer states")
    states: list[str] = Field(
        default_factory=list,
        description="Customer state codes sold to, sorted alphabetically",
    )
    distributor_count: int = Field(default=0, description="Count of distinct distributors")
    distributors: list[str] = Field(
        default_factory=list,
        description="Distributor names sold through, sorted alphabetically",
    )


class ProductPerformanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    products: list[ProductPerformance]
    total_revenue: Decimal = Field(description="Sum across all products in the result")


class StatePerformance(BaseModel):
    """Revenue contribution from a single US state (or NULL = unknown)."""

    model_config = ConfigDict(frozen=True)

    state_code: str | None = Field(
        description="2-letter state code; null when customer state is unknown",
    )
    revenue: Decimal
    cases: Decimal
    invoice_count: int
    customer_count: int
    pct_of_revenue: float


class StatePerformanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    states: list[StatePerformance]
    total_revenue: Decimal


class DistributorPerformance(BaseModel):
    """Revenue contribution from a single distributor / control-state / military buyer."""

    model_config = ConfigDict(frozen=True)

    distributor_id: int | None
    distributor_name: str | None
    channel: str | None = Field(
        description="distributor | control_state | military | other; null when unmapped",
    )
    revenue: Decimal
    cases: Decimal
    invoice_count: int
    customer_count: int
    pct_of_revenue: float


class DistributorPerformanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    distributors: list[DistributorPerformance]
    total_revenue: Decimal
