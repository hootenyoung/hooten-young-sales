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
        Query(description="Filter to entries with this action key."),
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
