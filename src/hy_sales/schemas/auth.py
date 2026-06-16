"""Pydantic request and response models for the auth API.

Conventions:
* Email is normalized to lowercase + stripped at the boundary via
  the shared ``EmailLower`` annotated type. This is the single source
  of truth for email normalization — no model needs to remember to
  ``.lower()`` itself.
* Password fields are constrained to ``[8, 128]`` characters. Tighter
  rules (uppercase / digit / special) are intentionally NOT enforced
  here because they add UX friction without measurably improving
  resistance to bcrypt-attacked dumps. Length is what matters most.
* All response models are ``frozen=True`` to match the convention
  used by the depletions schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
)


def _normalize_email(value: object) -> object:
    """Strip whitespace and lowercase the input if it's a string.

    Non-string values pass through unchanged so Pydantic's own
    validation can produce a clean error message for them.
    """
    if isinstance(value, str):
        return value.strip().lower()
    return value


# Shared annotated email type. Use this on EVERY field that accepts
# an email — never plain ``EmailStr`` — so normalization is uniform.
EmailLower = Annotated[EmailStr, BeforeValidator(_normalize_email)]

# Password constraint shared across signup / reset / change.
PasswordStr = Annotated[str, Field(min_length=8, max_length=128)]


# =====================================================================
# Request models
# =====================================================================


class SignupRequest(BaseModel):
    """Self-service signup. Account starts in ``pending`` status and
    cannot log in until an admin approves it.
    """

    email: EmailLower
    password: PasswordStr
    first_name: Annotated[str, Field(min_length=1, max_length=100)]
    last_name: Annotated[str, Field(min_length=1, max_length=100)]


class LoginRequest(BaseModel):
    email: EmailLower
    password: PasswordStr


class ForgotPasswordRequest(BaseModel):
    """Request a password-reset email. The endpoint always returns
    200 regardless of whether the email exists — avoids leaking
    which addresses have accounts.
    """

    email: EmailLower


class ResetPasswordRequest(BaseModel):
    """Consume a password-reset or set-password token to set a new
    password. ``token`` is the plaintext value from the email link.
    """

    token: Annotated[str, Field(min_length=16, max_length=128)]
    new_password: PasswordStr


class ChangePasswordRequest(BaseModel):
    """Authenticated password change. Requires the current password
    to defend against session-hijack-only attackers.
    """

    current_password: PasswordStr
    new_password: PasswordStr


# =====================================================================
# Response models
# =====================================================================


class RolePublic(BaseModel):
    """One role as exposed to clients (admin UI, /me)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    display_name: str
    description: str | None
    is_system: bool


class TokenResponse(BaseModel):
    """OAuth2-style bearer-token response. ``expires_in`` is seconds
    from now (per RFC 6749). ``must_change_password`` lets the client
    route directly to the change-password screen on first login.
    """

    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 RFC 6749 literal, not a password
    expires_in: int
    must_change_password: bool


class SignupResponse(BaseModel):
    """Returned by /auth/signup — no token because the account is
    pending admin approval and cannot log in yet.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    status: str
    message: str = "Signup successful. Awaiting admin approval."


class UserDetail(BaseModel):
    """Full user record + assigned roles. Used by /auth/me and by
    the admin user-list / user-detail endpoints.
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


class MessageResponse(BaseModel):
    """Generic ``{"message": "..."}`` response — used by /forgot-password
    and any endpoint that succeeds with nothing meaningful to return.
    """

    model_config = ConfigDict(frozen=True)

    message: str
