"""SQLAlchemy async engine and session factory.

A single engine is created at import time using the configured
``DATABASE_URL``. The engine does not actually open a connection
until a session needs one, so importing this module is safe even
without a reachable database.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from hy_sales.settings import get_settings


def _build_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        # Modest pool defaults; tune per Cloud Run instance.
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        # Echo all SQL only in DEBUG mode.
        echo=settings.log_level.upper() == "DEBUG",
    )


engine: AsyncEngine = _build_engine()

async_session_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)
