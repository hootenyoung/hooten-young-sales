"""Health-check endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales import __version__
from hy_sales.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness() -> dict[str, str]:
    """Liveness probe — does NOT touch the DB. Safe to hammer."""
    return {"status": "ok", "version": __version__}


@router.get("/health/ready")
async def readiness(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Readiness probe — verifies the DB is reachable.

    Use for Cloud Run readiness checks. Returns 500 if the DB is down.
    """
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__, "db": "reachable"}
