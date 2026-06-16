"""Admin endpoints for the role catalog.

Mounted at ``/api/admin/roles``. Router-level dependency requires the
``admin`` role.

Endpoints
---------
* ``GET   /``       — list every role + the count of users assigned.
* ``POST  /``       — create a non-system role.

System roles (``is_system=True``) seeded by migration 003 are visible
in the list but cannot be created here (UNIQUE name conflict) or
deleted (no DELETE endpoint exposed).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.auth.audit import audit_event
from hy_sales.auth.dependencies import CurrentUser, require_role
from hy_sales.db.session import get_session
from hy_sales.models import AuthRole, AuthUserRole
from hy_sales.schemas.admin import (
    AdminCreateRoleRequest,
    RoleListResponse,
    RoleWithUsage,
)

require_admin = require_role("admin")

router = APIRouter(
    prefix="/api/admin/roles",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ---------------------------------------------------------------------
# GET /api/admin/roles
# ---------------------------------------------------------------------


@router.get("", response_model=RoleListResponse)
async def list_roles(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoleListResponse:
    """All roles in the catalog, with usage counts."""
    stmt = (
        select(
            AuthRole.id,
            AuthRole.name,
            AuthRole.display_name,
            AuthRole.description,
            AuthRole.is_system,
            func.count(AuthUserRole.user_id).label("user_count"),
        )
        .outerjoin(AuthUserRole, AuthUserRole.role_id == AuthRole.id)
        .group_by(AuthRole.id)
        .order_by(AuthRole.is_system.desc(), AuthRole.name)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        RoleWithUsage(
            id=r.id,
            name=r.name,
            display_name=r.display_name,
            description=r.description,
            is_system=r.is_system,
            user_count=r.user_count,
        )
        for r in rows
    ]
    return RoleListResponse(items=items)


# ---------------------------------------------------------------------
# POST /api/admin/roles
# ---------------------------------------------------------------------


@router.post("", response_model=RoleWithUsage, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: AdminCreateRoleRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[CurrentUser, Depends(require_admin)],
) -> RoleWithUsage:
    """Add a new non-system role."""
    existing = await session.execute(select(AuthRole).where(AuthRole.name == payload.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "role_name_taken", "message": "A role with this name already exists."},
        )

    role = AuthRole(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        is_system=False,
    )
    session.add(role)
    await session.flush()

    audit_event(
        session,
        action="role_created",
        user_id=actor.id,
        metadata={
            "role_id": str(role.id),
            "role_name": role.name,
            "created_by": str(actor.id),
        },
        request=request,
    )

    return RoleWithUsage(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        is_system=role.is_system,
        user_count=0,
    )
