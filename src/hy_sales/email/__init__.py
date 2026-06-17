"""Outbound transactional email — invitations + password-reset links.

Single public entry point is :func:`send_reset_email`.  When the
SendGrid API key is unset (local dev without secrets) the function
falls back to a structlog event and never raises, so reset/invitation
flows keep working without external dependencies.

Templates are pure-Python f-string interpolation rather than a
template engine — the bodies are small and version-controlled with
the code, and avoiding Jinja keeps the dependency surface minimal.
"""

from hy_sales.email.client import (
    send_admin_signup_notification,
    send_feedback_email,
    send_reset_email,
)

__all__ = [
    "send_admin_signup_notification",
    "send_feedback_email",
    "send_reset_email",
]
