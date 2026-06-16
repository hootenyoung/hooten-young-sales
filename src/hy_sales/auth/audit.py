"""Shared auth-event helpers used by the auth router and the admin
router.

Lives in the auth package (not api) because these are domain helpers,
not HTTP handlers. Both api/auth.py and api/admin_*.py import from
here so the audit-row shape, the reset-link emission, and the
user-detail materialization are uniform across surfaces.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import AuthAuditLog, AuthRole, AuthUser, AuthUserRole
from hy_sales.schemas.auth import RolePublic, UserDetail
from hy_sales.settings import Settings

_log = structlog.get_logger(__name__)


def client_ip(request: Request | None) -> str | None:
    """Best-effort client IP. Falls back to the socket peer."""
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def audit_event(
    session: AsyncSession,
    *,
    action: str,
    user_id: Any | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Append a row to auth.audit_log.

    Commits with the surrounding session — caller doesn't need to
    flush. Pass ``request`` if you want IP + user-agent captured.
    """
    session.add(
        AuthAuditLog(
            user_id=user_id,
            action=action,
            metadata_=metadata or {},
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent") if request else None,
        )
    )


def log_reset_link(
    *,
    email: str,
    plaintext_token: str,
    purpose: str,
    settings: Settings,
) -> str:
    """Stub for the password-reset / set-password email.

    Builds the URL the user would click, emits a structured structlog
    event at INFO level so it shows up in dev server output, and
    returns the URL — the admin-creates-user flow returns the URL in
    its response while SendGrid wiring is deferred to Phase 4.
    """
    reset_url = f"{settings.frontend_reset_url}?token={plaintext_token}"
    _log.info(
        "auth.reset_link_issued",
        email=email,
        purpose=purpose,
        reset_url=reset_url,
        ttl_hours=settings.password_reset_ttl_hours,
    )
    return reset_url


async def load_user_detail(session: AsyncSession, user: AuthUser) -> UserDetail:
    """Materialize a ``UserDetail`` for ``user`` (loads roles).

    Used by /api/auth/me and the admin endpoints — keeps the
    user-+-roles projection consistent everywhere it's exposed.
    """
    role_rows = await session.execute(
        select(AuthRole)
        .join(AuthUserRole, AuthUserRole.role_id == AuthRole.id)
        .where(AuthUserRole.user_id == user.id)
        .order_by(AuthRole.name)
    )
    roles = [
        RolePublic(
            id=r.id,
            name=r.name,
            display_name=r.display_name,
            description=r.description,
            is_system=r.is_system,
        )
        for r in role_rows.scalars().all()
    ]
    return UserDetail(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        status=user.status,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        roles=roles,
    )
