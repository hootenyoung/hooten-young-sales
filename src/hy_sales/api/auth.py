"""Auth endpoints: signup, login, /me, forgot-password, reset-password, change-password.

Mounted at ``/api/auth``. Every endpoint that mutates state writes a
row to ``auth.audit_log``.

Token / reset-link semantics:
* ``/login`` and ``/change-password`` and ``/reset-password`` return a
  fresh JWT so the client always gets a token whose
  ``must_change_password`` claim reflects current state.
* ``/forgot-password`` always returns 200 regardless of whether the
  email exists — avoids email enumeration. Reset links are issued
  via :func:`issue_reset_link`, which logs the URL and (when SendGrid
  is configured) sends the templated email.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.auth.audit import audit_event, client_ip, issue_reset_link, load_user_detail
from hy_sales.auth.dependencies import CurrentUser, get_current_user
from hy_sales.db.session import get_session
from hy_sales.email import send_admin_signup_notification
from hy_sales.models import (
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
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UpdateMeRequest,
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

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------
# Local helpers (used only by this router)
# ---------------------------------------------------------------------


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
    settings: Annotated[Settings, Depends(get_settings)],
) -> SignupResponse:
    """Self-service signup. Account is created in ``pending`` status
    and CANNOT log in until an admin approves it.

    After persisting the request, every active admin receives an email
    pointing at the Pending Approvals tab — closes the loop so a
    signup doesn't sit unnoticed.  Email delivery is best-effort:
    failures are logged but never block the signup itself.
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

    audit_event(
        session,
        action="signup_submitted",
        user_id=user.id,
        metadata={"email": user.email},
        request=request,
    )

    await _notify_admins_of_pending_signup(session=session, requester=user, settings=settings)

    return SignupResponse(user_id=user.id, status=user.status)


async def _notify_admins_of_pending_signup(
    *,
    session: AsyncSession,
    requester: AuthUser,
    settings: Settings,
) -> None:
    """Email every active admin about the new pending request.

    Best-effort: SendGrid failures are swallowed (and logged by the
    client) so a transient delivery problem can't block the signup
    itself — the admin can still see the request in /admin/pending.
    """
    admins = (
        (
            await session.execute(
                select(AuthUser)
                .join(AuthUserRole, AuthUserRole.user_id == AuthUser.id)
                .join(AuthRole, AuthRole.id == AuthUserRole.role_id)
                .where(AuthRole.name == "admin")
                .where(AuthUser.status == "active")
            )
        )
        .scalars()
        .all()
    )

    if not admins:
        # Edge case — bootstrap state before the first admin is seeded.
        # The signup still succeeds; we just have no one to notify.
        return

    requested_at_display = datetime.now(UTC).strftime("%b %d, %Y at %I:%M %p UTC")

    for admin in admins:
        try:
            await send_admin_signup_notification(
                recipient_email=admin.email,
                recipient_first_name=admin.first_name,
                requester_first_name=requester.first_name,
                requester_last_name=requester.last_name,
                requester_email=requester.email,
                requested_at_display=requested_at_display,
                reference_url=settings.frontend_reset_url,
                settings=settings,
            )
        except Exception:  # noqa: S112 — log+continue is intentional; per-recipient delivery is best-effort and client already logs the full SendGrid response.
            continue


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
        audit_event(
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
        audit_event(
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
    audit_event(
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
    return await load_user_detail(session, user)


@router.patch("/me", response_model=UserDetail)
async def update_me(
    payload: UpdateMeRequest,
    request: Request,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserDetail:
    """Self-update of identity fields (first_name + last_name).

    Email is NOT changeable here — that's a separate flow that
    requires re-verification. Roles + status are admin-only.
    """
    user = await session.get(AuthUser, current.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Snapshot for audit log.
    old = {"first_name": user.first_name, "last_name": user.last_name}
    user.first_name = payload.first_name
    user.last_name = payload.last_name

    audit_event(
        session,
        action="profile_updated",
        user_id=user.id,
        metadata={
            "old": old,
            "new": {"first_name": payload.first_name, "last_name": payload.last_name},
        },
        request=request,
    )

    return await load_user_detail(session, user)


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
    audit_event(
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
                requested_by_ip=client_ip(request),
            )
        )
        # Forgot-password: the email is the user's only delivery
        # channel, so propagate failures as 5xx — the form retries
        # cleanly on the frontend.
        await issue_reset_link(
            email=user.email,
            first_name=user.first_name,
            plaintext_token=plaintext,
            purpose="forgot_password",
            settings=settings,
            raise_on_send_failure=True,
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
        audit_event(
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

    audit_event(
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
        audit_event(
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
    audit_event(
        session,
        action="password_changed",
        user_id=user.id,
        request=request,
    )
    return _issue_token(user, settings)
