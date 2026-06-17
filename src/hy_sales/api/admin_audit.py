"""Admin endpoint for the audit log.

Mounted at ``/api/admin/audit-log``. Router-level dependency requires
the ``admin`` role.

The log is append-only (never updated, never deleted), sorted newest
first. Pagination is cursor-based on the row id — pass the ``id`` of
the last row returned as ``cursor`` to fetch the page before it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.auth.dependencies import require_role
from hy_sales.db.session import get_session
from hy_sales.models import AuthAuditLog, AuthUser
from hy_sales.schemas.admin import AuditLogEntry, AuditLogResponse

require_admin = require_role("admin")

router = APIRouter(
    prefix="/api/admin/audit-log",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

# Friendly category → set of underlying action keys. Used by the admin
# UI to present a small set of meaningful filter chips ("Sign-ins",
# "Passwords") instead of one dropdown listing every raw action.
# When both ``action`` and ``category`` are supplied, ``action`` wins
# because it's the more specific filter.
CATEGORY_ACTIONS: dict[str, list[str]] = {
    "signins": ["login_success", "login_failed"],
    "signups": [
        "signup_submitted",
        "signup_approved",
        "signup_rejected",
        "admin_created_user",
    ],
    "passwords": [
        "password_changed",
        "password_change_failed",
        "password_set",
        "password_reset_requested",
        "password_reset_failed",
        "admin_initiated_password_reset",
        "admin_invitation_resent",
    ],
    "roles": ["roles_changed", "role_created"],
    "admin_actions": [
        "admin_created_user",
        "admin_initiated_password_reset",
        "admin_invitation_resent",
        "admin_updated_user_profile",
        "signup_approved",
        "signup_rejected",
        "account_disabled",
        "account_enabled",
        "role_created",
    ],
    "security": [
        "login_failed",
        "password_reset_failed",
        "password_change_failed",
    ],
}


@router.get("", response_model=AuditLogResponse)
async def list_audit_log(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[
        int | None,
        Query(description="ID of the last row from the previous page (exclusive)."),
    ] = None,
    action: Annotated[
        str | None,
        Query(description="Filter to entries with this single action key."),
    ] = None,
    category: Annotated[
        str | None,
        Query(
            description=(
                "Filter to entries whose action falls in this category. "
                f"Recognised values: {', '.join(CATEGORY_ACTIONS)}. Ignored if "
                "``action`` is also supplied."
            ),
        ),
    ] = None,
    user_id: Annotated[
        str | None,
        Query(description="Filter to entries for this user UUID."),
    ] = None,
    since: Annotated[
        datetime | None,
        Query(description="Lower bound on occurred_at (inclusive)."),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(description="Upper bound on occurred_at (inclusive)."),
    ] = None,
) -> AuditLogResponse:
    """Paginated audit-log read with filters.

    Cursor pagination means rows are returned in descending id order
    (newest first); the cursor is the last id from the previous page.
    Filtering by date does NOT change the cursor semantics — it just
    narrows the rows considered for pagination.
    """
    stmt = (
        select(AuthAuditLog, AuthUser.email)
        .outerjoin(AuthUser, AuthUser.id == AuthAuditLog.user_id)
        .order_by(AuthAuditLog.id.desc())
        .limit(limit + 1)  # +1 to know whether there's a next page
    )

    if cursor is not None:
        stmt = stmt.where(AuthAuditLog.id < cursor)
    if action:
        stmt = stmt.where(AuthAuditLog.action == action)
    elif category and category in CATEGORY_ACTIONS:
        stmt = stmt.where(AuthAuditLog.action.in_(CATEGORY_ACTIONS[category]))
    if user_id:
        stmt = stmt.where(AuthAuditLog.user_id == user_id)
    if since:
        stmt = stmt.where(AuthAuditLog.occurred_at >= since)
    if until:
        stmt = stmt.where(AuthAuditLog.occurred_at <= until)

    rows = (await session.execute(stmt)).all()

    has_next = len(rows) > limit
    rows = rows[:limit]

    # SQLAlchemy returns INET columns as ipaddress.IPv4Address /
    # IPv6Address instances; the Pydantic schema wants plain str
    # because the API contract is "render-friendly". Cast at the
    # response-build site rather than weakening the schema.
    items = [
        AuditLogEntry(
            id=row.AuthAuditLog.id,
            user_id=row.AuthAuditLog.user_id,
            user_email=row.email,
            action=row.AuthAuditLog.action,
            metadata=row.AuthAuditLog.metadata_,
            ip_address=(
                str(row.AuthAuditLog.ip_address)
                if row.AuthAuditLog.ip_address is not None
                else None
            ),
            user_agent=row.AuthAuditLog.user_agent,
            occurred_at=row.AuthAuditLog.occurred_at,
        )
        for row in rows
    ]
    next_cursor = items[-1].id if has_next and items else None
    return AuditLogResponse(items=items, next_cursor=next_cursor)
