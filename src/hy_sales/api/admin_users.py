"""Admin endpoints for user lifecycle management.

Mounted at ``/api/admin/users``. Router-level dependency requires the
``admin`` role on every request; non-admins get the structured 403
``missing_role`` body from :func:`require_role`.

Endpoints
---------
* ``GET    /``                — paginated, filterable users list.
* ``GET    /{id}``            — full UserDetail for one user.
* ``POST   /``                — admin-creates-user → issues a set-password
                                token; the URL is returned in the response
                                (and logged via structlog stub) so the admin
                                can deliver it manually until Phase 4 wires
                                SendGrid.
* ``PATCH  /{id}/roles``      — replace a user's role assignments.
* ``PATCH  /{id}/status``     — change lifecycle state (approve / reject /
                                disable / re-enable).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.auth.audit import audit_event, client_ip, load_user_detail, log_reset_link
from hy_sales.auth.dependencies import CurrentUser, require_role
from hy_sales.db.session import get_session
from hy_sales.models import AuthPasswordResetToken, AuthRole, AuthUser, AuthUserRole
from hy_sales.schemas.admin import (
    AdminCreateUserRequest,
    AdminCreateUserResponse,
    AdminUpdateUserRolesRequest,
    AdminUpdateUserStatusRequest,
    UserListItem,
    UserListResponse,
)
from hy_sales.schemas.auth import RolePublic, UserDetail
from hy_sales.security import generate_reset_token, hash_password
from hy_sales.settings import Settings, get_settings

# Every endpoint requires the `admin` role. The dependency factory
# returns the current admin user as the CurrentUser type, exposed as
# ``actor`` in handlers for audit-log attribution.
require_admin = require_role("admin")

router = APIRouter(
    prefix="/api/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


async def _materialize_list_item(session: AsyncSession, user: AuthUser) -> UserListItem:
    """Build a ``UserListItem`` (includes the user's roles)."""
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
    return UserListItem(
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


async def _replace_user_roles(
    session: AsyncSession,
    user_id: object,
    role_ids: list[object],
    assigned_by: object,
) -> list[str]:
    """Replace all of ``user_id``'s role assignments with ``role_ids``.

    Returns the list of role names assigned (for audit logging).
    Raises 400 if any role_id doesn't exist.
    """
    if role_ids:
        present = (
            await session.execute(
                select(AuthRole.id, AuthRole.name).where(AuthRole.id.in_(role_ids))
            )
        ).all()
        if len(present) != len(set(role_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "unknown_role", "message": "One or more role IDs are unknown."},
            )
        names = [row.name for row in present]
    else:
        names = []

    # Wipe-and-replace. Composite PK (user_id, role_id) makes this
    # simple; for thousands of role rows we'd diff, but here the set
    # is always ≤ 10.
    await session.execute(delete(AuthUserRole).where(AuthUserRole.user_id == user_id))
    for rid in role_ids:
        session.add(
            AuthUserRole(
                user_id=user_id,
                role_id=rid,
                assigned_by=assigned_by,
            )
        )
    # autoflush is off on the session factory, so flush here so the
    # caller's subsequent role-loading SELECT sees the new rows.
    await session.flush()
    return names


# ---------------------------------------------------------------------
# GET /api/admin/users
# ---------------------------------------------------------------------


@router.get("", response_model=UserListResponse)
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description="Filter by user status (pending/active/rejected/disabled).",
        ),
    ] = None,
    role: Annotated[
        str | None,
        Query(description="Filter to users assigned the given role name."),
    ] = None,
    search: Annotated[
        str | None,
        Query(description="Case-insensitive substring match on email + name."),
    ] = None,
) -> UserListResponse:
    """Paginated user list with status/role/search filters."""
    base = select(AuthUser)
    count_base = select(func.count(AuthUser.id))

    if status_filter:
        base = base.where(AuthUser.status == status_filter)
        count_base = count_base.where(AuthUser.status == status_filter)

    if role:
        role_subq = (
            select(AuthUserRole.user_id)
            .join(AuthRole, AuthRole.id == AuthUserRole.role_id)
            .where(AuthRole.name == role)
        ).scalar_subquery()
        base = base.where(AuthUser.id.in_(role_subq))
        count_base = count_base.where(AuthUser.id.in_(role_subq))

    if search:
        pattern = f"%{search.lower()}%"
        # email is already lowercase; first/last_name aren't, so lower() them.
        where_search = (
            AuthUser.email.like(pattern)
            | func.lower(AuthUser.first_name).like(pattern)
            | func.lower(AuthUser.last_name).like(pattern)
        )
        base = base.where(where_search)
        count_base = count_base.where(where_search)

    total = (await session.execute(count_base)).scalar_one()
    rows = (
        (
            await session.execute(
                base.order_by(AuthUser.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )

    items = [await _materialize_list_item(session, u) for u in rows]
    return UserListResponse(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------
# GET /api/admin/users/{id}
# ---------------------------------------------------------------------


@router.get("/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserDetail:
    user = await session.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await load_user_detail(session, user)


# ---------------------------------------------------------------------
# POST /api/admin/users — admin-creates-user
# ---------------------------------------------------------------------


@router.post("", response_model=AdminCreateUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminCreateUserRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    actor: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminCreateUserResponse:
    """Admin creates a new active user.

    No password is set; the user receives a one-time set-password link
    (24h TTL). Until SendGrid is wired (Phase 4), the URL is returned
    in the response so the admin can hand-deliver it.
    """
    existing = await session.execute(select(AuthUser).where(AuthUser.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "email_taken", "message": "An account with this email already exists."},
        )

    # Random un-guessable hash so the column is NOT NULL but no one
    # can log in with this account until they consume the set-password
    # token.
    placeholder_password = secrets.token_urlsafe(32)

    user = AuthUser(
        email=payload.email,
        password_hash=hash_password(placeholder_password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        status="active",
        must_change_password=True,
        created_by=actor.id,
    )
    session.add(user)
    await session.flush()

    role_names = await _replace_user_roles(
        session,
        user_id=user.id,
        role_ids=list(payload.role_ids),
        assigned_by=actor.id,
    )

    plaintext, digest = generate_reset_token()
    expires_at = datetime.now(UTC) + timedelta(hours=settings.password_reset_ttl_hours)
    session.add(
        AuthPasswordResetToken(
            user_id=user.id,
            token_hash=digest,
            purpose="set_password",
            expires_at=expires_at,
            requested_by_ip=client_ip(request),
        )
    )
    set_password_url = log_reset_link(
        email=user.email,
        plaintext_token=plaintext,
        purpose="set_password",
        settings=settings,
    )

    audit_event(
        session,
        action="admin_created_user",
        user_id=user.id,
        metadata={
            "email": user.email,
            "created_by": str(actor.id),
            "roles": role_names,
        },
        request=request,
    )

    detail = await load_user_detail(session, user)
    return AdminCreateUserResponse(
        user=detail,
        set_password_url=set_password_url,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------
# PATCH /api/admin/users/{id}/roles
# ---------------------------------------------------------------------


@router.patch("/{user_id}/roles", response_model=UserDetail)
async def update_user_roles(
    user_id: str,
    payload: AdminUpdateUserRolesRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[CurrentUser, Depends(require_admin)],
) -> UserDetail:
    user = await session.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Snapshot the old roles for audit log.
    old_role_names = (
        (
            await session.execute(
                select(AuthRole.name)
                .join(AuthUserRole, AuthUserRole.role_id == AuthRole.id)
                .where(AuthUserRole.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )

    new_role_names = await _replace_user_roles(
        session,
        user_id=user.id,
        role_ids=list(payload.role_ids),
        assigned_by=actor.id,
    )

    audit_event(
        session,
        action="roles_changed",
        user_id=user.id,
        metadata={
            "changed_by": str(actor.id),
            "old_roles": sorted(old_role_names),
            "new_roles": sorted(new_role_names),
        },
        request=request,
    )

    return await load_user_detail(session, user)


# ---------------------------------------------------------------------
# PATCH /api/admin/users/{id}/status
# ---------------------------------------------------------------------


# Per-status: what action name to record + which previous statuses
# we accept as the "from" side of the transition. This is what makes
# the transitions safe — admins can't move users into arbitrary
# states (e.g. you can't move a `disabled` user back to `pending`).
_STATUS_TRANSITIONS = {
    ("pending", "active"): "signup_approved",
    ("pending", "rejected"): "signup_rejected",
    ("active", "disabled"): "account_disabled",
    ("disabled", "active"): "account_enabled",
    ("rejected", "active"): "signup_approved",
}


@router.patch("/{user_id}/status", response_model=UserDetail)
async def update_user_status(
    user_id: str,
    payload: AdminUpdateUserStatusRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[CurrentUser, Depends(require_admin)],
) -> UserDetail:
    user = await session.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.status == payload.status:
        # No-op; don't write an audit row, but return the current state.
        return await load_user_detail(session, user)

    action = _STATUS_TRANSITIONS.get((user.status, payload.status))
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_status_transition",
                "message": f"Cannot move user from {user.status!r} to {payload.status!r}.",
            },
        )

    old_status = user.status
    user.status = payload.status
    audit_event(
        session,
        action=action,
        user_id=user.id,
        metadata={
            "changed_by": str(actor.id),
            "old_status": old_status,
            "new_status": payload.status,
        },
        request=request,
    )

    return await load_user_detail(session, user)
