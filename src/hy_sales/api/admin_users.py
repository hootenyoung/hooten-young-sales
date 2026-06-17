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
from typing import Annotated, Any

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
    AdminIssueResetResponse,
    AdminUpdateUserProfileRequest,
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
    sort_by: Annotated[
        str,
        Query(
            description="Column to sort by: name | last_sign_in | created | status | email.",
        ),
    ] = "created",
    sort_dir: Annotated[
        str,
        Query(description="Sort direction: asc | desc."),
    ] = "desc",
) -> UserListResponse:
    """Paginated user list with status/role/search filters + sorting."""
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

    # Sort ──────────────────────────────────────────────────────────
    # Map UI sort keys to the underlying ORM columns. Anything not
    # in this map falls back to created_at DESC so a malformed query
    # param can't break the page.
    sort_columns = {
        "name": (AuthUser.first_name, AuthUser.last_name),
        "email": (AuthUser.email,),
        "status": (AuthUser.status,),
        "last_sign_in": (AuthUser.last_login_at,),
        "created": (AuthUser.created_at,),
    }
    cols = sort_columns.get(sort_by, sort_columns["created"])
    descending = sort_dir.lower() != "asc"
    # last_sign_in is nullable — pin NULLs to the bottom regardless
    # of direction so users who've never signed in don't dominate the
    # asc page.
    order_terms: list[Any] = []
    for c in cols:
        if c is AuthUser.last_login_at:
            order_terms.append(c.desc().nullslast() if descending else c.asc().nullslast())
        else:
            order_terms.append(c.desc() if descending else c.asc())
    # Stable secondary sort so equal primary keys come back in a
    # deterministic order across page boundaries.
    order_terms.append(AuthUser.id.asc())
    base = base.order_by(*order_terms)

    total = (await session.execute(count_base)).scalar_one()
    rows = (await session.execute(base.limit(limit).offset(offset))).scalars().all()

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
# PATCH /api/admin/users/{id}/profile
# ---------------------------------------------------------------------


@router.patch("/{user_id}/profile", response_model=UserDetail)
async def update_user_profile(
    user_id: str,
    payload: AdminUpdateUserProfileRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[CurrentUser, Depends(require_admin)],
) -> UserDetail:
    """Admin-side edit of another user's display-name fields.

    Distinct audit action (``admin_updated_user_profile``) so the
    activity feed can render "an administrator updated this profile"
    instead of attributing the change to the user themselves.
    """
    user = await session.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old = {"first_name": user.first_name, "last_name": user.last_name}
    new = {"first_name": payload.first_name, "last_name": payload.last_name}

    # No-op if nothing actually changed — saves an audit row and a
    # write. Still returns the (unchanged) UserDetail so the client
    # doesn't have to special-case the response.
    if old == new:
        return await load_user_detail(session, user)

    user.first_name = payload.first_name
    user.last_name = payload.last_name

    audit_event(
        session,
        action="admin_updated_user_profile",
        user_id=user.id,
        metadata={"changed_by": str(actor.id), "old": old, "new": new},
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


# ---------------------------------------------------------------------
# POST /api/admin/users/{id}/reset-password
# ---------------------------------------------------------------------


async def _issue_reset_for_user(
    *,
    user: AuthUser,
    purpose: str,
    audit_action: str,
    actor: CurrentUser,
    session: AsyncSession,
    settings: Settings,
    request: Request,
) -> AdminIssueResetResponse:
    """Shared helper for admin-issued reset / invitation flows.

    Generates a fresh password-reset token (the existing schema row
    type — only `purpose` differs), flags the user so their next
    sign-in is forced to set a new password, logs the URL via the
    structlog stub, and writes an audit row attributing the action
    to the calling admin.
    """
    plaintext, digest = generate_reset_token()
    expires_at = datetime.now(UTC) + timedelta(hours=settings.password_reset_ttl_hours)
    session.add(
        AuthPasswordResetToken(
            user_id=user.id,
            token_hash=digest,
            purpose=purpose,
            expires_at=expires_at,
            requested_by_ip=client_ip(request),
        )
    )
    user.must_change_password = True

    reset_url = log_reset_link(
        email=user.email,
        plaintext_token=plaintext,
        purpose=purpose,
        settings=settings,
    )

    audit_event(
        session,
        action=audit_action,
        user_id=user.id,
        metadata={
            "actor_id": str(actor.id),
            "purpose": purpose,
            "email": user.email,
        },
        request=request,
    )

    detail = await load_user_detail(session, user)
    return AdminIssueResetResponse(
        user=detail,
        reset_url=reset_url,
        expires_at=expires_at,
        purpose=purpose,
    )


@router.post(
    "/{user_id}/reset-password",
    response_model=AdminIssueResetResponse,
)
async def reset_user_password(
    user_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    actor: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminIssueResetResponse:
    """Admin-initiated password reset.

    Issues a ``forgot_password`` token + sets ``must_change_password``,
    then returns the link. Until SendGrid is wired (Phase 4) the admin
    delivers the link manually (Slack, email, whatever). The user is
    forced to change their password on next sign-in; any active JWT
    they hold still works until they hit a ``must_change_password``-
    gated route, at which point they're redirected to ``/change-password``.

    Pending / rejected / disabled users can't have their password
    reset — they have to be approved or re-enabled first.
    """
    user = await session.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_user_status",
                "message": (
                    f"Cannot reset password for a user in status {user.status!r}. "
                    "Approve or re-enable them first."
                ),
            },
        )

    return await _issue_reset_for_user(
        user=user,
        purpose="forgot_password",
        audit_action="admin_initiated_password_reset",
        actor=actor,
        session=session,
        settings=settings,
        request=request,
    )


# ---------------------------------------------------------------------
# POST /api/admin/users/{id}/resend-invitation
# ---------------------------------------------------------------------


@router.post(
    "/{user_id}/resend-invitation",
    response_model=AdminIssueResetResponse,
)
async def resend_user_invitation(
    user_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    actor: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminIssueResetResponse:
    """Re-issue a set-password invitation for a user who hasn't yet
    set their initial password.

    Only valid when ``must_change_password`` is True — i.e. the user
    was admin-created but never used their original link (it expired,
    got lost, etc.). For users who already set their password and just
    forgot it, use ``/reset-password`` instead.
    """
    user = await session.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "no_invitation_pending",
                "message": (
                    "This user has already set their password. Use a password reset instead."
                ),
            },
        )

    return await _issue_reset_for_user(
        user=user,
        purpose="set_password",
        audit_action="admin_invitation_resent",
        actor=actor,
        session=session,
        settings=settings,
        request=request,
    )
