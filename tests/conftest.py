"""Shared pytest configuration.

Sets required env vars before any hy_sales imports occur. Otherwise
``Settings()`` would raise at import time because no ``DATABASE_URL``
is set in the test environment.
"""

from __future__ import annotations

import os

# Stub env vars must be set BEFORE hy_sales is imported anywhere.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_db",
)
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("LOG_LEVEL", "WARNING")
