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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton accessor for app settings.

    Use this from FastAPI dependencies (preferred) or anywhere else
    that needs settings at runtime. Cached so we don't re-parse env on
    every call.
    """
    # values populated from env at runtime; pydantic-settings handles validation
    return Settings()
