"""Auth endpoints: signup, login, /me, forgot-password, reset-password, change-password.

Mounted at ``/api/auth``. Every endpoint that mutates state writes a
row to ``auth.audit_log``.

Token / reset-link semantics:
* ``/login`` and ``/change-password`` and ``/reset-password`` return a
  fresh JWT so the client always gets a token whose
  ``must_change_password`` claim reflects current state.
* ``/forgot-password`` always returns 200 regardless of whether the
  email exists — avoids email enumeration. Reset links are emitted
  via the stub in :func:`_log_reset_link` (real SendGrid wiring is
  Phase 4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.auth.dependencies import CurrentUser, get_current_user
from hy_sales.db.session import get_session
from hy_sales.models import (
    AuthAuditLog,
    AuthPasswordResetToken,
    AuthRole,
    AuthUser,
    AuthUserRole,
)
from hy_sales.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    RolePublic,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserDetail,
)
from hy_sales.security import (
    create_access_token,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from hy_sales.settings import Settings, get_settings

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP. Falls back to the socket peer."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _audit(
    session: AsyncSession,
    *,
    action: str,
    user_id: Any | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Append a row to auth.audit_log. Commit happens with the session."""
    session.add(
        AuthAuditLog(
            user_id=user_id,
            action=action,
            metadata_=metadata or {},
            ip_address=_client_ip(request) if request else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    )


def _log_reset_link(
    *,
    email: str,
    plaintext_token: str,
    purpose: str,
    settings: Settings,
) -> None:
    """Stub for the password-reset email.

    Logs the reset URL via structlog so a developer can copy it from
    server output during local development. Real SendGrid wiring
    happens in Phase 4 (Task #119). When that lands, this function
    will compose the email and send it; the log line will remain at
    DEBUG level as a development aid.
    """
    reset_url = f"{settings.frontend_reset_url}?token={plaintext_token}"
    log.info(
        "auth.reset_link_issued",
        email=email,
        purpose=purpose,
        reset_url=reset_url,
        ttl_hours=settings.password_reset_ttl_hours,
    )


async def _load_user_detail(session: AsyncSession, user: AuthUser) -> UserDetail:
    """Materialize a ``UserDetail`` for ``user`` (loads roles)."""
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


def _issue_token(user: AuthUser, settings: Settings) -> TokenResponse:
    token, expires_in = create_access_token(
        user.id,
        secret=settings.jwt_secret,
        ttl_hours=settings.jwt_access_ttl_hours,
        algorithm=settings.jwt_algorithm,
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        must_change_password=user.must_change_password,
    )


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    payload: SignupRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SignupResponse:
    """Self-service signup. Account is created in ``pending`` status
    and CANNOT log in until an admin approves it.
    """
    existing = await session.execute(select(AuthUser).where(AuthUser.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "email_taken", "message": "An account with this email already exists."},
        )

    user = AuthUser(
        email=payload.email,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        status="pending",
        must_change_password=False,
    )
    session.add(user)
    await session.flush()  # populate user.id

    _audit(
        session,
        action="signup_submitted",
        user_id=user.id,
        metadata={"email": user.email},
        request=request,
    )

    return SignupResponse(user_id=user.id, status=user.status)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Email + password login. Returns a JWT on success.

    Failure modes:
    * Unknown email or wrong password → 401 ``invalid_credentials``
    * status is ``pending`` / ``rejected`` / ``disabled`` → 403 with
      a code matching the status so the frontend can show the right
      explanation.
    """
    result = await session.execute(select(AuthUser).where(AuthUser.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        _audit(
            session,
            action="login_failed",
            user_id=user.id if user else None,
            metadata={"email": payload.email, "reason": "invalid_credentials"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Invalid email or password."},
        )

    if user.status != "active":
        _audit(
            session,
            action="login_failed",
            user_id=user.id,
            metadata={"email": payload.email, "reason": f"status_{user.status}"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": f"account_{user.status}",
                "message": f"Account status: {user.status}.",
            },
        )

    user.last_login_at = datetime.now(UTC)
    _audit(
        session,
        action="login_success",
        user_id=user.id,
        metadata={"email": user.email},
        request=request,
    )
    return _issue_token(user, settings)


@router.get("/me", response_model=UserDetail)
async def me(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserDetail:
    """Return the full record for the authenticated caller, including roles.

    Works even when ``must_change_password=True`` so the change-password
    screen can display the user's identity.
    """
    user = await session.get(AuthUser, current.id)
    if user is None:
        # Race: deleted between token decode and now. Treat as 401.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return await _load_user_detail(session, user)


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MessageResponse:
    """Issue a reset-password email if the address belongs to an active
    user. ALWAYS returns 200 (no email enumeration).
    """
    result = await session.execute(select(AuthUser).where(AuthUser.email == payload.email))
    user = result.scalar_one_or_none()

    # Always audit the attempt, even for unknown emails (forensics).
    _audit(
        session,
        action="password_reset_requested",
        user_id=user.id if user else None,
        metadata={"email": payload.email, "user_found": user is not None},
        request=request,
    )

    if user is not None and user.status == "active":
        plaintext, digest = generate_reset_token()
        expires_at = datetime.now(UTC) + timedelta(hours=settings.password_reset_ttl_hours)
        session.add(
            AuthPasswordResetToken(
                user_id=user.id,
                token_hash=digest,
                purpose="forgot_password",
                expires_at=expires_at,
                requested_by_ip=_client_ip(request),
            )
        )
        _log_reset_link(
            email=user.email,
            plaintext_token=plaintext,
            purpose="forgot_password",
            settings=settings,
        )

    return MessageResponse(
        message="If an account exists for that email, a reset link has been sent."
    )


@router.post("/reset-password", response_model=TokenResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Consume a password-reset / set-password token and set the new
    password. Returns a fresh JWT so the user lands logged in.

    Failure modes:
    * Unknown token → 400 ``invalid_token``
    * Token already used → 400 ``invalid_token``
    * Token expired → 400 ``invalid_token``

    All three collapse to one error code so an attacker can't
    distinguish (timing attacks on token state).
    """
    digest = hash_reset_token(payload.token)
    result = await session.execute(
        select(AuthPasswordResetToken).where(AuthPasswordResetToken.token_hash == digest)
    )
    reset_row = result.scalar_one_or_none()

    now = datetime.now(UTC)
    invalid = reset_row is None or reset_row.used_at is not None or reset_row.expires_at <= now
    if invalid:
        _audit(
            session,
            action="password_reset_failed",
            user_id=reset_row.user_id if reset_row else None,
            metadata={"reason": "invalid_token"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_token", "message": "Reset link is invalid or has expired."},
        )

    assert reset_row is not None  # narrowed by the check above
    user = await session.get(AuthUser, reset_row.user_id)
    if user is None:
        # The user was deleted between issuing the token and using it.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_token", "message": "Reset link is invalid or has expired."},
        )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    reset_row.used_at = now

    _audit(
        session,
        action="password_set",
        user_id=user.id,
        metadata={"purpose": reset_row.purpose},
        request=request,
    )

    return _issue_token(user, settings)


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Authenticated password change. Verifies the current password
    so a session-hijacked attacker can't trivially lock the user out.
    Returns a fresh JWT (so ``must_change_password=False`` is reflected
    in the new token's response payload).
    """
    user = await session.get(AuthUser, current.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not verify_password(payload.current_password, user.password_hash):
        _audit(
            session,
            action="password_change_failed",
            user_id=user.id,
            metadata={"reason": "wrong_current_password"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "wrong_current_password",
                "message": "Current password is incorrect.",
            },
        )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    _audit(
        session,
        action="password_changed",
        user_id=user.id,
        request=request,
    )
    return _issue_token(user, settings)
