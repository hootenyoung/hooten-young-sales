"""Application settings loaded from environment variables.

Uses pydantic-settings so missing required vars cause an immediate,
descriptive error at startup rather than surprising failures at runtime.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values come from (in priority order):
      1. Process environment variables.
      2. ``.env.local`` (gitignored, local dev only).
      3. Defaults defined here.
    """

    model_config = SettingsConfigDict(
        env_file=(".env.local",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Database -------------------------------------------------
    database_url: str = Field(
        ...,
        description=("Async Postgres URL. Format: postgresql+asyncpg://user:pass@host:5432/db"),
    )

    # ---- Runtime --------------------------------------------------
    app_env: str = Field(
        default="local",
        description="Environment name: local | dev | prod",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG | INFO | WARNING | ERROR",
    )

    # ---- Authentication / JWT -------------------------------------
    # Signing secret for JWT access tokens. MUST be a long random
    # string in prod (>=64 chars). Generate with: openssl rand -hex 64
    # Different secret per environment; rotating it invalidates every
    # existing token, forcing a re-login.
    jwt_secret: str = Field(
        ...,
        description="HMAC signing secret for JWT access tokens. Required.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm. HS256 = HMAC-SHA256 with jwt_secret.",
    )
    jwt_access_ttl_hours: int = Field(
        default=24,
        description=(
            "Access token lifetime in hours. No refresh tokens; user re-logs in after expiry."
        ),
    )

    # ---- Password reset / set-password ----------------------------
    # TTL for both the forgot-password flow and the admin-creates-user
    # set-password flow. The same auth.password_reset_tokens table
    # powers both; the `purpose` column distinguishes them.
    password_reset_ttl_hours: int = Field(
        default=24,
        description="Password reset / set-password token lifetime in hours.",
    )

    # Frontend URL where password-reset emails point. The token is
    # appended as ?token=<plaintext>. E.g.:
    #   local: http://localhost:5173/auth/reset-password
    #   dev:   https://dashboard-dev.hootenyoung.com/auth/reset-password
    #   prod:  https://dashboard.hootenyoung.com/auth/reset-password
    frontend_reset_url: str = Field(
        ...,
        description="Frontend URL for password-reset links. Token is appended as ?token=...",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton accessor for app settings.

    Use this from FastAPI dependencies (preferred) or anywhere else
    that needs settings at runtime. Cached so we don't re-parse env on
    every call.
    """
    # values populated from env at runtime; pydantic-settings handles validation
    return Settings()
