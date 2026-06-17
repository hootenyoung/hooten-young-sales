"""Pydantic request and response models for the admin API.

Conventions:
* Email fields reuse the shared ``EmailLower`` annotated type from
  ``schemas.auth`` so normalization is uniform across both surfaces.
* All response models are ``frozen=True`` matching the rest of the
  codebase.
* Pagination uses ``limit + offset`` for the users + roles lists
  (small datasets, simpler clients) and ``cursor`` for the audit log
  (potentially large, append-only stream).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hy_sales.schemas.auth import EmailLower, RolePublic, UserDetail

# =====================================================================
# Users
# =====================================================================


class UserListItem(BaseModel):
    """Compact user record for the admin list view.

    Excludes ``password_hash`` (obviously) and large nullable fields
    that aren't useful in a table. The full record is available via
    /admin/users/{id} which returns ``UserDetail`` (shared with /me).
    """

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    status: str
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[RolePublic]


class UserListResponse(BaseModel):
    """Paginated users response."""

    model_config = ConfigDict(frozen=True)

    items: list[UserListItem]
    total: int
    limit: int
    offset: int


class AdminCreateUserRequest(BaseModel):
    """Admin-creates-user payload.

    Backend creates the user with ``status='active'`` and
    ``must_change_password=True`` (no real password set), issues a
    ``set_password`` token, and emails the invitation to the user via
    SendGrid.  The link is also returned in the response as a fallback.
    """

    email: EmailLower
    first_name: Annotated[str, Field(min_length=1, max_length=100)]
    last_name: Annotated[str, Field(min_length=1, max_length=100)]
    role_ids: list[uuid.UUID] = Field(default_factory=list)


class AdminUpdateUserRolesRequest(BaseModel):
    """Replace a user's role assignments with the given set."""

    role_ids: list[uuid.UUID]


class AdminUpdateUserProfileRequest(BaseModel):
    """Admin-side edit of another user's display-name fields.

    Mirrors the self-update ``UpdateMeRequest`` scope on purpose —
    email changes go through a separate verification flow and roles +
    status have their own dedicated admin endpoints. Keeping this
    payload minimal avoids ambiguity in the audit log: every entry
    under ``admin_updated_user_profile`` is a name-only edit.
    """

    first_name: Annotated[str, Field(min_length=1, max_length=100)]
    last_name: Annotated[str, Field(min_length=1, max_length=100)]


class AdminUpdateUserStatusRequest(BaseModel):
    """Move a user between lifecycle states.

    Allowed transitions (enforced server-side):
      pending  → active | rejected
      active   → disabled
      rejected → active   (re-consider a previously rejected signup)
      disabled → active   (re-enable a former employee)
    """

    status: str

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        allowed = {"pending", "active", "rejected", "disabled"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}, got {v!r}")
        return v


class AdminCreateUserResponse(BaseModel):
    """Result of admin-creates-user.

    ``set_password_url`` is always populated so the admin has a
    fallback to hand-deliver the link via Slack / DM if SendGrid
    delivery fails (delivery is best-effort and does not block
    account creation).
    """

    model_config = ConfigDict(frozen=True)

    user: UserDetail
    set_password_url: str | None
    expires_at: datetime


class AdminIssueResetResponse(BaseModel):
    """Result of admin-triggered password reset or invitation resend.

    Shape matches ``AdminCreateUserResponse`` so the frontend can use
    the same success step.  The user is emailed the link via SendGrid;
    ``reset_url`` is also returned in the response as a fallback the
    admin can hand-deliver.  ``purpose`` reflects whether this was a
    forgot-password reset (``forgot_password``) or a fresh invitation
    (``set_password``).
    """

    model_config = ConfigDict(frozen=True)

    user: UserDetail
    reset_url: str | None
    expires_at: datetime
    purpose: str


# =====================================================================
# Roles
# =====================================================================


class AdminCreateRoleRequest(BaseModel):
    """Create a non-system role.

    ``name`` is the machine-readable identifier used in code + role
    checks (e.g. ``analyst``, ``forecasting``). Lowercased + stripped
    by the validator. System roles seeded by migration 003 cannot be
    created here (UNIQUE constraint on name).
    """

    name: Annotated[str, Field(min_length=1, max_length=50)]
    display_name: Annotated[str, Field(min_length=1, max_length=100)]
    description: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v


class RoleWithUsage(BaseModel):
    """Role + count of users currently assigned. Used by the admin UI
    so admins know how many people are affected before they delete /
    reorganize a role.
    """

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    display_name: str
    description: str | None
    is_system: bool
    user_count: int


class RoleListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[RoleWithUsage]


# =====================================================================
# Audit log
# =====================================================================


class AuditLogEntry(BaseModel):
    """One audit-log row, enriched with the actor's email for display."""

    model_config = ConfigDict(frozen=True)

    id: int
    user_id: uuid.UUID | None
    user_email: str | None
    action: str
    metadata: dict[str, Any]
    ip_address: str | None
    user_agent: str | None
    occurred_at: datetime


class AuditLogResponse(BaseModel):
    """Cursor-paginated audit log.

    ``next_cursor`` is the ``id`` of the last row returned; pass it as
    the ``cursor`` query param on the next request to fetch the page
    after it. Sorted by ``occurred_at DESC`` (newest first); cursor
    iterates backwards in time through the stream.
    """

    model_config = ConfigDict(frozen=True)

    items: list[AuditLogEntry]
    next_cursor: int | None
