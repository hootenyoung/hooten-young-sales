"""Depletions read endpoints — power the dashboard's Depletions tab."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.db.session import get_session
from hy_sales.schemas.depletions import (
    DepletionsKPIs,
    DepletionsProductPerformance,
    DepletionsProductResponse,
    DepletionsStatePerformance,
    DepletionsStateResponse,
    DepletionsTrendPoint,
    DepletionsTrendResponse,
    TopAccount,
    TopAccountsResponse,
)
from hy_sales.schemas.strategic import (
    FollowUpTrackerResponse,
    NewVsLostAccountsResponse,
    VelocityAnalysisResponse,
)
from hy_sales.services.depletions_queries import (
    get_depletions_by_product,
    get_depletions_by_state,
    get_depletions_kpis,
    get_depletions_monthly_trend,
    get_top_accounts,
)
from hy_sales.services.strategic_queries import (
    get_follow_up_tracker,
    get_new_vs_lost_accounts,
    get_velocity_analysis,
)

router = APIRouter(prefix="/api/depletions", tags=["depletions"])


DateFromParam = Annotated[
    date | None,
    Query(alias="from", description="Inclusive lower bound on period_month (YYYY-MM-DD)."),
]
DateToParam = Annotated[
    date | None,
    Query(alias="to", description="Inclusive upper bound on period_month (YYYY-MM-DD)."),
]


@router.get(
    "/kpis",
    response_model=DepletionsKPIs,
    summary="Top-line depletions KPIs.",
)
async def kpis(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> DepletionsKPIs:
    data = await get_depletions_kpis(session, date_from=date_from, date_to=date_to)
    return DepletionsKPIs.model_validate(data)


@router.get(
    "/trend",
    response_model=DepletionsTrendResponse,
    summary="Monthly depletion volume time series.",
)
async def trend(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    grain: Annotated[
        str,
        Query(description="Bucket size; only 'month' supported today.", pattern="^month$"),
    ] = "month",
) -> DepletionsTrendResponse:
    points = await get_depletions_monthly_trend(session, date_from=date_from, date_to=date_to)
    return DepletionsTrendResponse(
        grain=grain,
        points=[DepletionsTrendPoint.model_validate(p) for p in points],
    )


@router.get(
    "/by-product",
    response_model=DepletionsProductResponse,
    summary="Depletion volume per product, sorted by 9L desc.",
)
async def by_product(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> DepletionsProductResponse:
    rows = await get_depletions_by_product(session, date_from=date_from, date_to=date_to)
    total_9l: Decimal = sum((r["cases_9l"] for r in rows), Decimal("0"))
    products = [
        DepletionsProductPerformance(
            product_id=r["product_id"],
            product_name=r["product_name"],
            cases_9l=r["cases_9l"],
            cases_physical=r["cases_physical"],
            account_count=r["account_count"],
            state_count=r["state_count"],
            pct_of_9l=float(r["cases_9l"] / total_9l) if total_9l > 0 else 0.0,
        )
        for r in rows
    ]
    return DepletionsProductResponse(products=products, total_9l=total_9l)


@router.get(
    "/by-state",
    response_model=DepletionsStateResponse,
    summary="Depletion volume per state, sorted by 9L desc.",
)
async def by_state(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
) -> DepletionsStateResponse:
    rows = await get_depletions_by_state(session, date_from=date_from, date_to=date_to)
    total_9l: Decimal = sum((r["cases_9l"] for r in rows), Decimal("0"))
    states = [
        DepletionsStatePerformance(
            state_code=r["state_code"],
            cases_9l=r["cases_9l"],
            cases_physical=r["cases_physical"],
            account_count=r["account_count"],
            pct_of_9l=float(r["cases_9l"] / total_9l) if total_9l > 0 else 0.0,
        )
        for r in rows
    ]
    return DepletionsStateResponse(states=states, total_9l=total_9l)


@router.get(
    "/top-accounts",
    response_model=TopAccountsResponse,
    summary="Top retail accounts by 9L depletion volume.",
)
async def top_accounts(
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> TopAccountsResponse:
    rows = await get_top_accounts(session, date_from=date_from, date_to=date_to, limit=limit)
    total_9l: Decimal = sum((r["cases_9l"] for r in rows), Decimal("0"))
    accounts = [
        TopAccount(
            account_id=r["account_id"],
            name=r["name"],
            state_code=r["state_code"],
            city=r["city"],
            distributor_name=r["distributor_name"],
            cases_9l=r["cases_9l"],
            cases_physical=r["cases_physical"],
            product_count=r["product_count"],
            last_active_period=r["last_active_period"],
            pct_of_9l=float(r["cases_9l"] / total_9l) if total_9l > 0 else 0.0,
        )
        for r in rows
    ]
    return TopAccountsResponse(accounts=accounts, total_9l=total_9l)


@router.get(
    "/follow-ups",
    response_model=FollowUpTrackerResponse,
    summary="Accounts bucketed by days since their last depletion period.",
)
async def follow_ups(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FollowUpTrackerResponse:
    data = await get_follow_up_tracker(session)
    return FollowUpTrackerResponse.model_validate(data)


@router.get(
    "/new-vs-lost",
    response_model=NewVsLostAccountsResponse,
    summary="Accounts gained / lost between two adjacent depletion windows.",
)
async def new_vs_lost(
    session: Annotated[AsyncSession, Depends(get_session)],
    window_months: Annotated[
        int,
        Query(ge=1, le=12, description="Length in months of each comparison window."),
    ] = 3,
) -> NewVsLostAccountsResponse:
    data = await get_new_vs_lost_accounts(session, window_months=window_months)
    return NewVsLostAccountsResponse.model_validate(data)


@router.get(
    "/velocity",
    response_model=VelocityAnalysisResponse,
    summary="Per-account depletion velocity (accelerating / steady / declining).",
)
async def velocity(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VelocityAnalysisResponse:
    data = await get_velocity_analysis(session)
    return VelocityAnalysisResponse.model_validate(data)
