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

from hy_sales.email import send_reset_email
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


async def issue_reset_link(
    *,
    email: str,
    first_name: str,
    plaintext_token: str,
    purpose: str,
    settings: Settings,
    raise_on_send_failure: bool = False,
) -> str:
    """Build the reset URL, log it, and (when configured) email it.

    Returns the URL so callers can also surface it in their HTTP
    response — useful as a copy-paste fallback when SendGrid is
    misconfigured or the recipient's inbox is unreliable.

    ``raise_on_send_failure`` controls error propagation:

    * ``False`` (default) — used by ``admin_created_user`` and
      ``admin_issue_reset``: the URL is returned in the response so
      the admin can deliver it manually if SendGrid is down; we
      log the failure and proceed.
    * ``True`` — used by the public ``forgot-password`` flow: the
      user has no other delivery channel, so if SendGrid is down we
      surface a 5xx and the caller can try again.

    When ``settings.sendgrid_api_key`` is unset the function never
    raises and never hits the network — it just logs the link so
    local dev / tests keep working without secrets.
    """
    reset_url = f"{settings.frontend_reset_url}?token={plaintext_token}"

    _log.info(
        "auth.reset_link_issued",
        email=email,
        purpose=purpose,
        reset_url=reset_url,
        ttl_hours=settings.password_reset_ttl_hours,
    )

    try:
        await send_reset_email(
            recipient_email=email,
            recipient_first_name=first_name,
            reset_url=reset_url,
            purpose=purpose,
            settings=settings,
        )
    except Exception:
        # ``send_reset_email`` already logged the failure with
        # SendGrid's response body — we just decide whether to
        # propagate based on caller intent.
        if raise_on_send_failure:
            raise

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
