"""SendGrid REST client + the high-level :func:`send_reset_email`.

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

The function returns a bool: ``True`` if SendGrid accepted the
message, ``False`` if we ran in "log-only" mode.  Errors raise.
"""

from __future__ import annotations

import httpx
import structlog

from hy_sales.email.templates import render_reset_email
from hy_sales.settings import Settings

_log = structlog.get_logger(__name__)

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def send_reset_email(
    *,
    recipient_email: str,
    recipient_first_name: str,
    reset_url: str,
    purpose: str,
    settings: Settings,
) -> bool:
    """Send (or log) a password-reset / set-password / admin-reset email.

    Returns ``True`` on successful SendGrid acceptance, ``False`` when
    SendGrid isn't configured (log-only path).  Network or 4xx/5xx
    errors propagate as ``httpx.HTTPError``.
    """
    rendered = render_reset_email(
        purpose=purpose,
        recipient_first_name=recipient_first_name,
        reset_url=reset_url,
        ttl_hours=settings.password_reset_ttl_hours,
    )

    # Log-only path — useful in local dev / unit tests, never raises
    # so the surrounding flow keeps working without secrets.
    if not settings.sendgrid_api_key:
        _log.info(
            "email.skipped_no_sendgrid_key",
            recipient=recipient_email,
            purpose=purpose,
            subject=rendered.subject,
            reset_url=reset_url,
        )
        return False

    payload: dict[str, object] = {
        "personalizations": [
            {
                "to": [{"email": recipient_email}],
                "subject": rendered.subject,
            }
        ],
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
        # Surface the email's intent in SendGrid analytics — makes
        # deliverability triage easier if a category misbehaves.
        "categories": ["auth", f"auth_{purpose}"],
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
        # SendGrid returns a JSON body explaining the failure — surface
        # it in the log so we can debug deliverability issues without
        # leaking the API key.
        _log.error(
            "email.sendgrid_rejected",
            recipient=recipient_email,
            purpose=purpose,
            status_code=exc.response.status_code,
            body=exc.response.text[:500],
        )
        raise
    except httpx.HTTPError as exc:
        _log.error(
            "email.sendgrid_transport_error",
            recipient=recipient_email,
            purpose=purpose,
            error=str(exc),
        )
        raise

    _log.info(
        "email.sent",
        recipient=recipient_email,
        purpose=purpose,
        subject=rendered.subject,
    )
    return True
