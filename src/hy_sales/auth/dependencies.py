"""FastAPI dependencies for authenticated routes.

Flow:

1. Client sends ``Authorization: Bearer <jwt>``.
2. ``get_current_user`` extracts the token, decodes it, loads the user
   record + their role names from the DB, and returns a frozen
   ``CurrentUser`` value.
3. Routes that need a specific role wrap the user dep with
   ``require_role('depletions')`` or ``require_any_role('admin', 'sales')``.

Design choices encoded here:

* **Re-check status every request.** A JWT issued while the user was
  active stays decodable for 24h, but an admin who disables the user
  needs that change to take effect immediately. Status check happens
  on every authenticated request.

* **Roles loaded fresh from DB, never from the JWT.** Same reason —
  role changes take effect immediately, not at next token rotation.
  Cost is one indexed query per request (sub-ms on this volume).

* **No admin override.** The ``admin`` role does NOT implicitly grant
  ``distribution`` / ``depletions`` / ``marketing``. The seed gives the
  bootstrap admin all four; future admins must be explicitly granted
  whatever they need. Explicit beats clever.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.db.session import get_session
from hy_sales.models import AuthRole, AuthUser, AuthUserRole
from hy_sales.security import decode_access_token
from hy_sales.settings import Settings, get_settings

# tokenUrl is the path of the login endpoint; OpenAPI uses it to
# wire up the "Authorize" button in /docs. The endpoint itself will
# live at /api/auth/login (created in Task #117).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller, as exposed to route handlers.

    Roles are a ``frozenset`` of role NAMES (not UUIDs) so handlers
    and gates can do cheap ``'depletions' in user.roles`` checks.
    """

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    status: str
    must_change_password: bool
    roles: frozenset[str]

    def has_role(self, name: str) -> bool:
        return name in self.roles

    def has_any_role(self, *names: str) -> bool:
        return not self.roles.isdisjoint(names)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    """Decode the bearer token, load the user, return a ``CurrentUser``.

    Raises:
      * 401 — token missing / malformed / expired / signature invalid /
              referenced user doesn't exist any more
      * 403 — user status is not 'active' (pending / rejected / disabled)

    Does NOT enforce ``must_change_password`` — that's deliberately
    permissive so the /me and /change-password endpoints work for users
    in that state. Resource gates (``require_role``) enforce it.
    """
    try:
        user_id = decode_access_token(
            token,
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    user = await session.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": f"account_{user.status}", "message": f"Account status: {user.status}"},
        )

    role_rows = await session.execute(
        select(AuthRole.name)
        .join(AuthUserRole, AuthUserRole.role_id == AuthRole.id)
        .where(AuthUserRole.user_id == user.id)
    )
    role_names = frozenset(role_rows.scalars().all())

    return CurrentUser(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        status=user.status,
        must_change_password=user.must_change_password,
        roles=role_names,
    )


def _must_change_password_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "must_change_password",
            "message": (
                "Password change required before accessing other resources. "
                "Call POST /api/auth/change-password first."
            ),
        },
    )


def _missing_role_error(required: str | tuple[str, ...]) -> HTTPException:
    required_str = required if isinstance(required, str) else ", ".join(required)
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "missing_role", "message": f"Required role(s): {required_str}"},
    )


ADMIN_ROLE = "admin"


def require_role(role_name: str) -> Any:
    """Factory: returns a dependency that 403s unless the user has ``role_name``.

    The ``admin`` role is treated as a wildcard — admins implicitly
    pass any role check. This matches admin's product semantics
    ("full platform access") and avoids the surprise where a user
    granted the ``admin`` role still gets 403 on a ``depletions``-
    gated route because they weren't separately granted ``depletions``.

    Usage::

        @router.get("/foo", dependencies=[Depends(require_role("depletions"))])
        async def get_foo(...):
            ...

    Or apply at router-level via ``APIRouter(dependencies=[Depends(require_role(...))])``
    to gate every endpoint under that router.
    """

    async def dep(
        user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if user.must_change_password:
            raise _must_change_password_error()
        if user.has_role(ADMIN_ROLE):
            return user
        if not user.has_role(role_name):
            raise _missing_role_error(role_name)
        return user

    return dep


def require_any_role(*role_names: str) -> Any:
    """Factory: returns a dependency that 403s unless the user has ANY of ``role_names``.

    Useful for endpoints that multiple roles should access (e.g. an
    overview page reachable by both ``distribution`` and ``depletions``
    users)::

        gate = Depends(require_any_role("distribution", "depletions"))

        @router.get("/overview", dependencies=[gate])
        async def overview(...):
            ...
    """
    if not role_names:
        raise ValueError("require_any_role needs at least one role")

    async def dep(
        user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if user.must_change_password:
            raise _must_change_password_error()
        # Admin wildcard — see require_role docstring.
        if user.has_role(ADMIN_ROLE):
            return user
        if not user.has_any_role(*role_names):
            raise _missing_role_error(role_names)
        return user

    return dep
