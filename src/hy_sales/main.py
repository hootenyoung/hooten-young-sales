"""FastAPI application entrypoint.

Run locally:

    uv run uvicorn hy_sales.main:app --reload --port 8000
"""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hy_sales import __version__
from hy_sales.api.admin_audit import router as admin_audit_router
from hy_sales.api.admin_roles import router as admin_roles_router
from hy_sales.api.admin_users import router as admin_users_router
from hy_sales.api.auth import router as auth_router
from hy_sales.api.depletions import router as depletions_router
from hy_sales.api.feedback import router as feedback_router
from hy_sales.api.health import router as health_router
from hy_sales.api.platform_config import router as platform_config_router
from hy_sales.api.sales import router as sales_router
from hy_sales.settings import get_settings


def _configure_logging(level: str) -> None:
    """Configure structlog + stdlib logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )


def create_app() -> FastAPI:
    """Build the FastAPI app instance."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    fastapi_app = FastAPI(
        title="Hooten Young Sales API",
        version=__version__,
        description=(
            "Sales + depletions backend for the Hooten Young dashboard. "
            "See CLAUDE.md for project context."
        ),
    )
    # CORS — let the dashboard SPA call us from its own origin.
    # Allowed origins:
    #   - localhost (any port) for local dev
    #   - *.run.app for Cloud Run direct URLs (used until DNS is wired)
    #   - ops.hootenyoung.com (prod) + ops-dev.hootenyoung.com (dev)
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^https?://("
            r"localhost(:\d+)?"
            r"|.*\.run\.app"
            r"|(ops|ops-dev)\.hootenyoung\.com"
            r")$"
        ),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    fastapi_app.include_router(health_router)
    fastapi_app.include_router(auth_router)
    fastapi_app.include_router(admin_users_router)
    fastapi_app.include_router(admin_roles_router)
    fastapi_app.include_router(admin_audit_router)
    fastapi_app.include_router(feedback_router)
    fastapi_app.include_router(platform_config_router)
    fastapi_app.include_router(sales_router)
    fastapi_app.include_router(depletions_router)
    return fastapi_app


app = create_app()
