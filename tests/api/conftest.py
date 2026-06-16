"""Fixtures for the API integration tests.

Tests in this directory hit the real dev Postgres database (the one
``DATABASE_URL`` in ``.env.local`` points at). They create their own
data prefixed ``test+<random>@example.com`` and tear it down after
each test.

The teardown carefully deletes:

  1. ``auth.audit_log`` rows referencing the test users — the FK has
     no ``ON DELETE CASCADE`` so this must happen first.
  2. ``auth.users`` rows themselves — ``user_roles`` and
     ``password_reset_tokens`` cascade automatically.

A session-scoped autouse cleaner catches anything created by direct
SQL inserts that didn't go through the ``create_user`` fixture.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from hy_sales.db.engine import async_session_factory
from hy_sales.main import create_app
from hy_sales.models import (
    AuthAuditLog,
    AuthRole,
    AuthUser,
    AuthUserRole,
)
from hy_sales.security import hash_password


def make_test_email() -> str:
    """Return a fresh ``test+<10hex>@example.com`` address."""
    return f"test+{secrets.token_hex(5)}@example.com"


@pytest_asyncio.fixture(scope="session")
async def app() -> Any:
    return create_app()


@pytest_asyncio.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    """httpx client bound to the FastAPI app via ASGI transport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


CreateUserFn = Callable[..., Awaitable[tuple[AuthUser, str]]]


@pytest_asyncio.fixture
async def create_user() -> AsyncIterator[CreateUserFn]:
    """Factory: create a test user directly in the DB.

    Usage::

        user, password = await create_user(roles=["depletions"], status="active")

    All users created via this factory are auto-cleaned at test teardown,
    along with their audit-log rows.
    """
    created_ids: list[Any] = []

    async def _make(
        *,
        email: str | None = None,
        password: str = "Test@1234",
        roles: list[str] | None = None,
        status: str = "active",
        must_change_password: bool = False,
    ) -> tuple[AuthUser, str]:
        async with async_session_factory() as s:
            user = AuthUser(
                email=email or make_test_email(),
                password_hash=hash_password(password),
                first_name="Test",
                last_name="User",
                status=status,
                must_change_password=must_change_password,
            )
            s.add(user)
            await s.flush()

            if roles:
                role_rows = (
                    (await s.execute(select(AuthRole).where(AuthRole.name.in_(roles))))
                    .scalars()
                    .all()
                )
                for r in role_rows:
                    s.add(AuthUserRole(user_id=user.id, role_id=r.id))

            await s.commit()
            await s.refresh(user)
            created_ids.append(user.id)
            return user, password

    yield _make

    if created_ids:
        async with async_session_factory() as s:
            await s.execute(delete(AuthAuditLog).where(AuthAuditLog.user_id.in_(created_ids)))
            await s.execute(delete(AuthUser).where(AuthUser.id.in_(created_ids)))
            await s.commit()


@pytest_asyncio.fixture(autouse=True)
async def _scrub_orphan_test_users() -> AsyncIterator[None]:
    """Belt-and-suspenders: catch anything the per-test factory missed."""
    yield
    async with async_session_factory() as s:
        orphan_ids = (
            (await s.execute(select(AuthUser.id).where(AuthUser.email.like("test+%@example.com"))))
            .scalars()
            .all()
        )
        if orphan_ids:
            await s.execute(delete(AuthAuditLog).where(AuthAuditLog.user_id.in_(orphan_ids)))
            await s.execute(delete(AuthUser).where(AuthUser.id.in_(orphan_ids)))
            await s.commit()


async def login(client: AsyncClient, email: str, password: str) -> str:
    """Helper: POST /api/auth/login and return the access token."""
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    assert isinstance(token, str)
    return token
