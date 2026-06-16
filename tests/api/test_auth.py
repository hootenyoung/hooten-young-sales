"""Integration tests for the /api/auth/* router and role-gated routes.

These tests hit the real dev Postgres database (see tests/api/conftest.py).
Every test creates its own ``test+<random>@example.com`` users and
cleans up after itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from hy_sales.db.engine import async_session_factory
from hy_sales.models import AuthPasswordResetToken, AuthUser
from hy_sales.security import generate_reset_token

from .conftest import CreateUserFn, login, make_test_email

# =====================================================================
# Signup
# =====================================================================


async def test_signup_creates_pending_user(client: AsyncClient) -> None:
    email = make_test_email()
    r = await client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "Test@1234",
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["user_id"]
    assert "Awaiting admin approval" in body["message"]


async def test_signup_duplicate_email_409(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    existing, _ = await create_user()
    r = await client.post(
        "/api/auth/signup",
        json={
            "email": existing.email,
            "password": "Another@1234",
            "first_name": "Other",
            "last_name": "Person",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "email_taken"


async def test_signup_normalizes_email_lowercase(client: AsyncClient) -> None:
    canonical = make_test_email()
    # Send mixed-case with leading/trailing whitespace.
    payload_email = f"  {canonical.upper()}  "
    r = await client.post(
        "/api/auth/signup",
        json={
            "email": payload_email,
            "password": "Test@1234",
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert r.status_code == 201
    async with async_session_factory() as s:
        row = (
            await s.execute(select(AuthUser).where(AuthUser.email == canonical))
        ).scalar_one_or_none()
        assert row is not None, f"expected normalized lowercase row for {canonical}"


# =====================================================================
# Login
# =====================================================================


async def test_login_pending_user_403(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(status="pending")
    r = await client.post("/api/auth/login", json={"email": user.email, "password": pw})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "account_pending"


async def test_login_wrong_password_401(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, _ = await create_user()
    r = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "wrong-password-here"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_credentials"


async def test_login_unknown_email_401(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/login",
        json={"email": make_test_email(), "password": "doesntmatter1234"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_credentials"


async def test_login_active_user_returns_token(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(roles=["depletions"])
    r = await client.post("/api/auth/login", json={"email": user.email, "password": pw})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 86400
    assert body["must_change_password"] is False
    assert len(body["access_token"]) > 50


# =====================================================================
# /me
# =====================================================================


async def test_me_with_valid_token(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(roles=["depletions", "marketing"])
    token = await login(client, user.email, pw)
    r = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == user.email
    assert body["status"] == "active"
    assert sorted(role["name"] for role in body["roles"]) == ["depletions", "marketing"]


async def test_me_with_bogus_token_401(client: AsyncClient) -> None:
    r = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r.status_code == 401


async def test_me_with_no_token_401(client: AsyncClient) -> None:
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


# =====================================================================
# Forgot password
# =====================================================================


async def test_forgot_password_unknown_email_200(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/forgot-password",
        json={"email": make_test_email()},
    )
    assert r.status_code == 200
    assert "reset link" in r.json()["message"]


async def test_forgot_password_creates_token_for_active_user(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, _ = await create_user()
    r = await client.post("/api/auth/forgot-password", json={"email": user.email})
    assert r.status_code == 200
    async with async_session_factory() as s:
        rows = (
            (
                await s.execute(
                    select(AuthPasswordResetToken).where(
                        AuthPasswordResetToken.user_id == user.id,
                        AuthPasswordResetToken.purpose == "forgot_password",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].used_at is None
        assert rows[0].expires_at > datetime.now(UTC)


# =====================================================================
# Reset password
# =====================================================================


async def _issue_reset_token(
    user_id: Any,
    *,
    purpose: str = "forgot_password",
    expires_in_hours: int = 24,
) -> str:
    """Insert a fresh reset token directly into the DB; return plaintext."""
    plaintext, digest = generate_reset_token()
    expires_at = datetime.now(UTC) + timedelta(hours=expires_in_hours)
    async with async_session_factory() as s:
        s.add(
            AuthPasswordResetToken(
                user_id=user_id,
                token_hash=digest,
                purpose=purpose,
                expires_at=expires_at,
            )
        )
        await s.commit()
    return plaintext


async def test_reset_password_consumes_token_and_logs_in(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, _ = await create_user(must_change_password=True)
    plaintext = await _issue_reset_token(user.id, purpose="set_password")

    r = await client.post(
        "/api/auth/reset-password",
        json={"token": plaintext, "new_password": "BrandNew@1234"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["must_change_password"] is False
    assert body["access_token"]

    # Login with the new password works.
    r2 = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "BrandNew@1234"},
    )
    assert r2.status_code == 200


async def test_reset_password_token_single_use(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, _ = await create_user()
    plaintext = await _issue_reset_token(user.id)

    # First use: success.
    r = await client.post(
        "/api/auth/reset-password",
        json={"token": plaintext, "new_password": "First@Use1234"},
    )
    assert r.status_code == 200

    # Second use: same token, should fail.
    r = await client.post(
        "/api/auth/reset-password",
        json={"token": plaintext, "new_password": "Second@Use1234"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_token"


async def test_reset_password_expired_token_rejected(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, _ = await create_user()
    plaintext = await _issue_reset_token(user.id, expires_in_hours=-1)

    r = await client.post(
        "/api/auth/reset-password",
        json={"token": plaintext, "new_password": "Whatever@1234"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_token"


async def test_reset_password_unknown_token_400(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/reset-password",
        json={"token": "a" * 32, "new_password": "Whatever@1234"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_token"


# =====================================================================
# Change password
# =====================================================================


async def test_change_password_wrong_current_401(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user()
    token = await login(client, user.email, pw)
    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "WrongPass1234", "new_password": "NewerPass1234"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "wrong_current_password"


async def test_change_password_success_clears_must_change(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(must_change_password=True)
    token = await login(client, user.email, pw)
    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": pw, "new_password": "NewerPass1234"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["must_change_password"] is False


# =====================================================================
# Route gating
# =====================================================================


async def test_depletions_route_requires_token(client: AsyncClient) -> None:
    r = await client.get("/api/depletions/kpis")
    assert r.status_code == 401


async def test_depletions_route_requires_depletions_role(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(roles=["marketing"])  # no depletions role
    token = await login(client, user.email, pw)
    r = await client.get(
        "/api/depletions/kpis",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "missing_role"


async def test_depletions_role_grants_access(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(roles=["depletions"])
    token = await login(client, user.email, pw)
    r = await client.get(
        "/api/depletions/kpis",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200


async def test_sales_route_requires_distribution_role(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(roles=["depletions"])  # missing distribution
    token = await login(client, user.email, pw)
    r = await client.get(
        "/api/sales/kpis",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


async def test_must_change_password_blocks_role_routes(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(roles=["depletions"], must_change_password=True)
    token = await login(client, user.email, pw)
    r = await client.get(
        "/api/depletions/kpis",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "must_change_password"


async def test_must_change_password_does_not_block_me(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    """The /me and /change-password endpoints must remain reachable for
    a user who's required to change their password — otherwise the flow
    is unrecoverable.
    """
    user, pw = await create_user(must_change_password=True)
    token = await login(client, user.email, pw)
    r = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
