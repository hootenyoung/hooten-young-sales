"""Sales read endpoints — power the dashboard's KPI strip + charts."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.db.session import get_session
from hy_sales.schemas.sales import (
    DistributorPerformance,
    DistributorPerformanceResponse,
    ProductPerformance,
    ProductPerformanceResponse,
    SalesKPIs,
    SalesTrendPoint,
    SalesTrendResponse,
    StatePerformance,
    StatePerformanceResponse,
)
from hy_sales.schemas.strategic import (
    OrderAnalysisResponse,
    RiskDashboardResponse,
    WhiteSpaceMatrixResponse,
)
from hy_sales.services.sales_queries import (
    get_sales_by_distributor,
    get_sales_by_product,
    get_sales_by_state,
    get_sales_kpis,
    get_sales_trend,
)
from hy_sales.services.strategic_queries import (
    get_order_analysis,
    get_risk_dashboard,
    get_white_space_matrix,
)

router = APIRouter(prefix="/api/sales", tags=["sales"])


DateFromParam = Annotated[
    date | None,
    Query(
        alias="from",
        description="Inclusive lower bound on invoice_date (YYYY-MM-DD).",
    ),
]
DateToParam = Annotated[
    date | None,
    Query(
        alias="to",
        description="Inclusive upper bound on invoice_date (YYYY-MM-DD).",
    ),
]


@router.get(
    "/kpis",
    response_model=SalesKPIs,
    summary="Top-line sales KPIs for a date range.",
)
async def kpis(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> SalesKPIs:
    """Returns total revenue, cases, commission, distinct counts, period bounds."""
    data = await get_sales_kpis(session, date_from=date_from, date_to=date_to)
    return SalesKPIs.model_validate(data)


@router.get(
    "/trend",
    response_model=SalesTrendResponse,
    summary="Sales time series, bucketed by month or week.",
)
async def trend(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    grain: Annotated[
        str,
        Query(
            description="Bucket size: 'month' or 'week' (ISO weeks).",
            pattern="^(month|week)$",
        ),
    ] = "month",
) -> SalesTrendResponse:
    """Time-bucketed revenue + cases + invoice count, ascending by period."""
    points = await get_sales_trend(
        session,
        date_from=date_from,
        date_to=date_to,
        grain=grain,
    )
    return SalesTrendResponse(
        grain=grain,
        points=[SalesTrendPoint.model_validate(p) for p in points],
    )


@router.get(
    "/by-product",
    response_model=ProductPerformanceResponse,
    summary="Revenue + cases per product, sorted by revenue desc.",
)
async def by_product(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    limit: Annotated[
        int | None,
        Query(ge=1, le=500, description="Cap the number of products returned."),
    ] = None,
) -> ProductPerformanceResponse:
    rows = await get_sales_by_product(
        session,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    total_revenue: Decimal = sum((r["revenue"] for r in rows), Decimal("0"))
    products: list[ProductPerformance] = []
    for r in rows:
        pct = float(r["revenue"] / total_revenue) if total_revenue > 0 else 0.0
        products.append(
            ProductPerformance(
                product_id=r["product_id"],
                product_name=r["product_name"],
                revenue=r["revenue"],
                cases=r["cases"],
                invoice_count=r["invoice_count"],
                pct_of_revenue=pct,
                avg_price_per_case=r.get("avg_price_per_case"),
                state_count=r.get("state_count", 0),
                states=r.get("states", []),
                distributor_count=r.get("distributor_count", 0),
                distributors=r.get("distributors", []),
            )
        )
    return ProductPerformanceResponse(
        products=products,
        total_revenue=total_revenue,
    )


@router.get(
    "/by-state",
    response_model=StatePerformanceResponse,
    summary="Revenue + cases per state, sorted by revenue desc.",
)
async def by_state(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> StatePerformanceResponse:
    rows = await get_sales_by_state(session, date_from=date_from, date_to=date_to)
    total_revenue: Decimal = sum((r["revenue"] for r in rows), Decimal("0"))
    states = [
        StatePerformance(
            state_code=r["state_code"],
            revenue=r["revenue"],
            cases=r["cases"],
            invoice_count=r["invoice_count"],
            customer_count=r["customer_count"],
            pct_of_revenue=float(r["revenue"] / total_revenue) if total_revenue > 0 else 0.0,
        )
        for r in rows
    ]
    return StatePerformanceResponse(states=states, total_revenue=total_revenue)


@router.get(
    "/by-distributor",
    response_model=DistributorPerformanceResponse,
    summary="Revenue + cases per distributor, sorted by revenue desc.",
)
async def by_distributor(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> DistributorPerformanceResponse:
    rows = await get_sales_by_distributor(session, date_from=date_from, date_to=date_to)
    total_revenue: Decimal = sum((r["revenue"] for r in rows), Decimal("0"))
    distributors = [
        DistributorPerformance(
            distributor_id=r["distributor_id"],
            distributor_name=r["distributor_name"],
            channel=r["channel"],
            revenue=r["revenue"],
            cases=r["cases"],
            invoice_count=r["invoice_count"],
            customer_count=r["customer_count"],
            pct_of_revenue=float(r["revenue"] / total_revenue) if total_revenue > 0 else 0.0,
        )
        for r in rows
    ]
    return DistributorPerformanceResponse(
        distributors=distributors,
        total_revenue=total_revenue,
    )


@router.get(
    "/white-space",
    response_model=WhiteSpaceMatrixResponse,
    summary="Product x state revenue matrix + gap statistics.",
)
async def white_space(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> WhiteSpaceMatrixResponse:
    data = await get_white_space_matrix(session, date_from=date_from, date_to=date_to)
    return WhiteSpaceMatrixResponse.model_validate(data)


@router.get(
    "/order-analysis",
    response_model=OrderAnalysisResponse,
    summary="Order-level rollups: size buckets, cross-sell, distributor frequency.",
)
async def order_analysis(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> OrderAnalysisResponse:
    data = await get_order_analysis(session, date_from=date_from, date_to=date_to)
    return OrderAnalysisResponse.model_validate(data)


@router.get(
    "/risk",
    response_model=RiskDashboardResponse,
    summary="Concentration metrics (top-N share + HHI) across product, distributor, state.",
)
async def risk_dashboard(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> RiskDashboardResponse:
    data = await get_risk_dashboard(session, date_from=date_from, date_to=date_to)
    return RiskDashboardResponse.model_validate(data)
