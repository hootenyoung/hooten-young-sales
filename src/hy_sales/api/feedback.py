"""POST /api/feedback — user-submitted feedback.

Persists every submission to ``auth.feedback`` as the source of truth,
then best-effort emails the configured recipient list (stored in
``platform.app_config['feedback_recipients']``).  Recipients can be
updated at runtime by editing that single config row — no redeploy.

Requires an authenticated user (any role).  The submitter's identity
(name + email) is attached to the email body so recipients can reply
directly to them.
"""

from __future__ import annotations

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.auth.dependencies import CurrentUser, get_current_user
from hy_sales.db.session import get_session
from hy_sales.email import send_feedback_email
from hy_sales.models import AuthFeedback, AuthUser, PlatformAppConfig
from hy_sales.schemas.feedback import FeedbackSubmitRequest, FeedbackSubmitResponse
from hy_sales.settings import Settings, get_settings

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


_RECIPIENTS_KEY = "feedback_recipients"


@router.post("", response_model=FeedbackSubmitResponse)
async def submit_feedback(
    payload: FeedbackSubmitRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FeedbackSubmitResponse:
    """Persist + dispatch a feedback submission."""
    # Materialise the submitter so the email can include their name + email.
    submitter = await session.get(AuthUser, current.id)
    if submitter is None:
        # Race: token decoded but user deleted between then and now.
        # Persist nothing and behave as if the auth dep failed.
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    row = AuthFeedback(
        user_id=submitter.id,
        category=payload.category,
        message=payload.message,
        page_path=payload.page_path,
        allow_followup=payload.allow_followup,
    )
    session.add(row)
    await session.flush()  # populate row.id + row.created_at

    recipients = await _load_feedback_recipients(session)
    dispatched_any = False

    if recipients:
        submitted_at_display = row.created_at.astimezone(UTC).strftime("%b %d, %Y at %I:%M %p UTC")
        for recipient in recipients:
            try:
                ok = await send_feedback_email(
                    recipient_email=recipient,
                    category=payload.category,
                    message=payload.message,
                    page_path=payload.page_path,
                    allow_followup=payload.allow_followup,
                    submitter_first_name=submitter.first_name,
                    submitter_last_name=submitter.last_name,
                    submitter_email=submitter.email,
                    submitted_at_display=submitted_at_display,
                    feedback_id=row.id,
                    settings=settings,
                )
            except Exception:  # noqa: S112 — log+continue is intentional; client already logged the SendGrid response.
                continue
            dispatched_any = dispatched_any or ok

    return FeedbackSubmitResponse(
        id=row.id,
        created_at=row.created_at,
        email_dispatched=dispatched_any,
    )


async def _load_feedback_recipients(session: AsyncSession) -> list[str]:
    """Read + parse the feedback_recipients config row.

    Stored as comma-separated emails in a single ``platform.app_config``
    row so it can be updated at runtime without a redeploy:

        UPDATE platform.app_config
           SET value = 'a@hootenyoung.com,b@hootenyoung.com'
         WHERE key   = 'feedback_recipients';

    Returns an empty list when the row is missing, is_active=False, or
    has no parseable addresses — the endpoint still succeeds (the DB
    row is the source of truth), it just doesn't send emails.
    """
    row = (
        await session.execute(
            select(PlatformAppConfig).where(
                PlatformAppConfig.key == _RECIPIENTS_KEY,
                PlatformAppConfig.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if row is None:
        return []

    return [email.strip() for email in row.value.split(",") if email.strip()]
