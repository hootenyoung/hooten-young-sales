"""Shared pytest configuration.

Hoists ``.env.local`` into ``os.environ`` BEFORE any ``hy_sales`` import
so integration tests get the real ``DATABASE_URL`` (and JWT/reset
settings) without having to source the file manually.

For workflows where ``.env.local`` is absent (e.g. unit-test-only CI),
stub values are still set via ``setdefault`` so ``Settings()``
instantiation doesn't crash at import time.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_env_local() -> None:
    """Read .env.local into os.environ (no override).

    pydantic-settings loads .env files lazily inside Settings() — too
    late for conftest to influence engine creation. And environment
    variables take precedence over .env values per pydantic-settings.
    So we hoist .env.local up to os.environ here, before any hy_sales
    import. ``setdefault`` means real env vars (CI, shell) still win
    over the file.
    """
    env_path = Path(__file__).parent.parent / ".env.local"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_local()

# Fall-back stubs for any keys still missing — unit tests that don't
# touch the DB still need Settings() to instantiate.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_db",
)
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("JWT_SECRET", "stub-secret-for-unit-tests-only-not-secure")
os.environ.setdefault("FRONTEND_RESET_URL", "http://localhost:5173/auth/reset-password")
