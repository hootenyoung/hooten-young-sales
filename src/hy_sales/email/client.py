"""SendGrid REST client + the high-level email-send functions.

Uses ``httpx.AsyncClient`` against the SendGrid v3 mail-send endpoint
rather than the official ``sendgrid`` Python SDK — the SDK is sync
and brings its own dependency chain.  All we need is one POST.

Behaviour:

* When :attr:`Settings.sendgrid_api_key` is **set**, the email is
  rendered + POSTed.  On HTTP error a structlog event is emitted and
  the exception is re-raised so callers can decide whether to fail
  the request or proceed (e.g. admin-creates-user proceeds even on
  delivery failure because the URL is also returned in the response).
* When it's **unset** (no key in env), the function just logs the
  would-be email payload at INFO level and returns ``False`` — handy
  for local dev / CI without depending on a live SendGrid account.

Each public function returns a bool: ``True`` if SendGrid accepted the
message, ``False`` if we ran in "log-only" mode.  Errors raise.
"""

from __future__ import annotations

import httpx
import structlog

from hy_sales.email.templates import (
    RenderedEmail,
    render_admin_signup_notification,
    render_reset_email,
)
from hy_sales.settings import Settings

_log = structlog.get_logger(__name__)

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def _post_to_sendgrid(
    *,
    recipient_email: str,
    rendered: RenderedEmail,
    settings: Settings,
    category: str,
    log_extra: dict[str, object] | None = None,
) -> bool:
    """Shared transport for every email kind.

    Returns ``True`` on success, ``False`` when SendGrid isn't
    configured (log-only path).  Network / 4xx / 5xx errors propagate
    as ``httpx.HTTPError`` so the caller can decide whether to retry
    or proceed.
    """
    extras: dict[str, object] = {"recipient": recipient_email, "category": category}
    if log_extra:
        extras.update(log_extra)

    if not settings.sendgrid_api_key:
        _log.info("email.skipped_no_sendgrid_key", subject=rendered.subject, **extras)
        return False

    payload: dict[str, object] = {
        "personalizations": [{"to": [{"email": recipient_email}], "subject": rendered.subject}],
        "from": {
            "email": settings.sendgrid_from_email,
            "name": settings.sendgrid_from_name,
        },
        "reply_to": {
            "email": settings.sendgrid_reply_to or settings.sendgrid_from_email,
        },
        "content": [
            {"type": "text/plain", "value": rendered.text_body},
            {"type": "text/html", "value": rendered.html_body},
        ],
        # Surface intent in SendGrid analytics — makes deliverability
        # triage easier if one category starts misbehaving.
        "categories": [category.split("_", 1)[0], category],
    }

    headers = {
        "Authorization": f"Bearer {settings.sendgrid_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(_SENDGRID_URL, json=payload, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _log.error(
            "email.sendgrid_rejected",
            status_code=exc.response.status_code,
            body=exc.response.text[:500],
            **extras,
        )
        raise
    except httpx.HTTPError as exc:
        _log.error("email.sendgrid_transport_error", error=str(exc), **extras)
        raise

    _log.info("email.sent", subject=rendered.subject, **extras)
    return True


async def send_reset_email(
    *,
    recipient_email: str,
    recipient_first_name: str,
    reset_url: str,
    purpose: str,
    settings: Settings,
) -> bool:
    """Send (or log) a password-reset / set-password / admin-reset email."""
    rendered = render_reset_email(
        purpose=purpose,
        recipient_first_name=recipient_first_name,
        reset_url=reset_url,
        ttl_hours=settings.password_reset_ttl_hours,
    )
    return await _post_to_sendgrid(
        recipient_email=recipient_email,
        rendered=rendered,
        settings=settings,
        category=f"auth_{purpose}",
        log_extra={"purpose": purpose, "reset_url": reset_url},
    )


async def send_admin_signup_notification(
    *,
    recipient_email: str,
    recipient_first_name: str,
    requester_first_name: str,
    requester_last_name: str,
    requester_email: str,
    requested_at_display: str,
    reference_url: str,
    settings: Settings,
) -> bool:
    """Send (or log) the "new sign-up request waiting" email to an admin.

    ``reference_url`` is any frontend URL — the function derives the
    dashboard origin from it to build both the logo URL and the
    "Review request" CTA, so each environment's email points at its
    own dashboard.  Caller usually passes :attr:`Settings.frontend_reset_url`.
    """
    rendered = render_admin_signup_notification(
        recipient_first_name=recipient_first_name,
        requester_first_name=requester_first_name,
        requester_last_name=requester_last_name,
        requester_email=requester_email,
        requested_at_display=requested_at_display,
        reference_url=reference_url,
    )
    return await _post_to_sendgrid(
        recipient_email=recipient_email,
        rendered=rendered,
        settings=settings,
        category="admin_signup_notification",
        log_extra={"requester_email": requester_email},
    )
