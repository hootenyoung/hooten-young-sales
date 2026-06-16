"""Integration tests for the /api/admin/* routers.

Covers the full admin user-lifecycle (list, approve, reject, disable,
re-enable, role-edit, admin-creates-user), the role catalog, and the
audit-log read endpoint.

Same dev-DB + test+ prefix pattern as test_auth.py.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from hy_sales.db.engine import async_session_factory
from hy_sales.models import AuthRole, AuthUser

from .conftest import CreateUserFn, login, make_test_email

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


async def _admin_token(client: AsyncClient, create_user: CreateUserFn) -> tuple[str, AuthUser]:
    """Create an admin user, log in, return (token, user)."""
    admin, pw = await create_user(roles=["admin"])
    token = await login(client, admin.email, pw)
    return token, admin


async def _role_id(name: str) -> Any:
    async with async_session_factory() as s:
        return (await s.execute(select(AuthRole.id).where(AuthRole.name == name))).scalar_one()


# ---------------------------------------------------------------------
# Auth + gating
# ---------------------------------------------------------------------


async def test_admin_routes_require_admin_role(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    user, pw = await create_user(roles=["depletions"])
    token = await login(client, user.email, pw)
    for path in ("/api/admin/users", "/api/admin/roles", "/api/admin/audit-log"):
        r = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403, f"{path}: expected 403, got {r.status_code}"
        assert r.json()["detail"]["code"] == "missing_role"


async def test_admin_routes_401_without_token(client: AsyncClient) -> None:
    for path in ("/api/admin/users", "/api/admin/roles", "/api/admin/audit-log"):
        r = await client.get(path)
        assert r.status_code == 401


# ---------------------------------------------------------------------
# GET /api/admin/users
# ---------------------------------------------------------------------


async def test_list_users_paginated_and_filterable(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    # Seed test fixtures we'll filter for.
    await create_user(status="pending")
    await create_user(roles=["depletions"])

    r = await client.get("/api/admin/users", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body
    assert body["limit"] == 50

    r = await client.get("/api/admin/users?status=pending", headers=auth)
    assert r.status_code == 200
    pending = r.json()["items"]
    assert all(u["status"] == "pending" for u in pending)
    assert len(pending) >= 1

    r = await client.get("/api/admin/users?role=depletions", headers=auth)
    assert r.status_code == 200
    deps = r.json()["items"]
    assert all(any(role["name"] == "depletions" for role in u["roles"]) for u in deps)


# ---------------------------------------------------------------------
# POST /api/admin/users (admin creates user)
# ---------------------------------------------------------------------


async def test_admin_create_user_issues_set_password_link(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}
    depletions_role_id = str(await _role_id("depletions"))

    email = make_test_email()
    r = await client.post(
        "/api/admin/users",
        headers=auth,
        json={
            "email": email,
            "first_name": "New",
            "last_name": "Hire",
            "role_ids": [depletions_role_id],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == email
    assert body["user"]["status"] == "active"
    assert body["user"]["must_change_password"] is True
    assert "?token=" in body["set_password_url"]

    # New user can't sign in until they consume the set-password token.
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "anything-they-might-guess"},
    )
    assert r.status_code == 401


async def test_admin_create_user_duplicate_email_409(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    existing, _ = await create_user()
    r = await client.post(
        "/api/admin/users",
        headers=auth,
        json={
            "email": existing.email,
            "first_name": "Dup",
            "last_name": "User",
            "role_ids": [],
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "email_taken"


# ---------------------------------------------------------------------
# PATCH /api/admin/users/{id}/status — lifecycle transitions
# ---------------------------------------------------------------------


async def test_approve_pending_user(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    pending, _ = await create_user(status="pending")
    r = await client.patch(
        f"/api/admin/users/{pending.id}/status",
        headers=auth,
        json={"status": "active"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"


async def test_reject_pending_user(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    pending, _ = await create_user(status="pending")
    r = await client.patch(
        f"/api/admin/users/{pending.id}/status",
        headers=auth,
        json={"status": "rejected"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


async def test_disable_then_reenable_user(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    target, _ = await create_user()
    r = await client.patch(
        f"/api/admin/users/{target.id}/status",
        headers=auth,
        json={"status": "disabled"},
    )
    assert r.status_code == 200

    r = await client.patch(
        f"/api/admin/users/{target.id}/status",
        headers=auth,
        json={"status": "active"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"


async def test_invalid_status_transition_rejected(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    target, _ = await create_user()  # active
    # active → pending is not in the transition table
    r = await client.patch(
        f"/api/admin/users/{target.id}/status",
        headers=auth,
        json={"status": "pending"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_status_transition"


# ---------------------------------------------------------------------
# PATCH /api/admin/users/{id}/roles
# ---------------------------------------------------------------------


async def test_update_user_roles(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    target, _ = await create_user(roles=["depletions"])
    new_roles = [
        str(await _role_id("distribution")),
        str(await _role_id("marketing")),
    ]
    r = await client.patch(
        f"/api/admin/users/{target.id}/roles",
        headers=auth,
        json={"role_ids": new_roles},
    )
    assert r.status_code == 200
    body = r.json()
    role_names = sorted(role["name"] for role in body["roles"])
    assert role_names == ["distribution", "marketing"]


async def test_update_user_roles_unknown_id_400(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    target, _ = await create_user()
    r = await client.patch(
        f"/api/admin/users/{target.id}/roles",
        headers=auth,
        json={"role_ids": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "unknown_role"


# ---------------------------------------------------------------------
# /api/admin/roles
# ---------------------------------------------------------------------


async def test_list_roles_includes_system_roles_and_usage_counts(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/admin/roles", headers=auth)
    assert r.status_code == 200
    items = r.json()["items"]
    names = {item["name"] for item in items}
    assert {"admin", "distribution", "depletions", "marketing"}.issubset(names)
    # Each item should have a non-negative user_count.
    assert all(item["user_count"] >= 0 for item in items)


async def test_create_role_then_delete_cleanup(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    import secrets as _s

    name = f"test_role_{_s.token_hex(3)}"
    r = await client.post(
        "/api/admin/roles",
        headers=auth,
        json={"name": name, "display_name": "Test Role", "description": "Created by test"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == name
    assert body["is_system"] is False

    # Duplicate name → 409.
    r = await client.post(
        "/api/admin/roles",
        headers=auth,
        json={"name": name.upper(), "display_name": "Dup"},  # name validator lowercases
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "role_name_taken"

    # Cleanup: delete the role directly (no DELETE endpoint).
    async with async_session_factory() as s:
        role = (await s.execute(select(AuthRole).where(AuthRole.name == name))).scalar_one()
        await s.delete(role)
        await s.commit()


# ---------------------------------------------------------------------
# /api/admin/audit-log
# ---------------------------------------------------------------------


async def test_audit_log_returns_chronological_entries(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/admin/audit-log?limit=20", headers=auth)
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert isinstance(items, list)
    if len(items) > 1:
        # newest first
        from itertools import pairwise

        for prev, curr in pairwise(items):
            assert prev["id"] > curr["id"]


async def test_audit_log_cursor_pagination(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _ = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/admin/audit-log?limit=2", headers=auth)
    assert r.status_code == 200
    body = r.json()
    if body["next_cursor"] is None:
        # Audit log too short to test cursor flow on this DB; skip.
        return
    cursor = body["next_cursor"]
    r2 = await client.get(f"/api/admin/audit-log?limit=2&cursor={cursor}", headers=auth)
    assert r2.status_code == 200
    body2 = r2.json()
    # Older entries — ids strictly less than the cursor.
    for entry in body2["items"]:
        assert entry["id"] < cursor


# ---------------------------------------------------------------------
# Verify the audit log captured what we did
# ---------------------------------------------------------------------


async def test_status_change_logged_to_audit(
    client: AsyncClient,
    create_user: CreateUserFn,
) -> None:
    token, _admin = await _admin_token(client, create_user)
    auth = {"Authorization": f"Bearer {token}"}

    pending, _ = await create_user(status="pending")
    r = await client.patch(
        f"/api/admin/users/{pending.id}/status",
        headers=auth,
        json={"status": "active"},
    )
    assert r.status_code == 200

    # Pull the most recent audit log entries — the latest should be
    # signup_approved for the pending user.
    r = await client.get("/api/admin/audit-log?limit=20", headers=auth)
    actions = [item["action"] for item in r.json()["items"]]
    assert "signup_approved" in actions
