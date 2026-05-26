"""FastAPI dependency for per-request async DB sessions.

Use in a route:

    @router.get("/foo")
    async def get_foo(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> ...:
        ...
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.db.engine import async_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a per-request session, committing on success / rolling back on error."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
