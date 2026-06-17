"""Render every transactional email to /tmp HTML files for human review.

Run with:  uv run python scripts/preview_emails.py

Outputs HTML files in /tmp/hy-email-previews/ — open in a browser to
see how each will render in Gmail / Outlook / Apple Mail.
"""

from __future__ import annotations

from pathlib import Path

from hy_sales.email.templates import (
    render_admin_signup_notification,
    render_reset_email,
)

OUT_DIR = Path("/tmp/hy-email-previews")  # noqa: S108 — dev-only preview artefacts

SAMPLE_RESET_URL = (
    "https://ops-dev.hootenyoung.com/auth/reset-password"
    "?token=abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"
)
SAMPLE_FIRST_NAME = "Prasad"
SAMPLE_TTL_HOURS = 24


PREVIEWS = [
    {
        "purpose": "set_password",
        "filename": "01_set_password_invitation.html",
        "caption": "Sent when an administrator invites a new user (admin-creates-user flow).",
    },
    {
        "purpose": "forgot_password",
        "filename": "02_forgot_password_self_service.html",
        "caption": "Sent when a user clicks 'Forgot password?' on the sign-in screen.",
    },
    {
        "purpose": "admin_initiated",
        "filename": "03_admin_initiated_reset.html",
        "caption": (
            "Sent when an administrator presses 'Send password reset' on an existing "
            "user from the admin panel."
        ),
    },
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for preview in PREVIEWS:
        rendered = render_reset_email(
            purpose=preview["purpose"],
            recipient_first_name=SAMPLE_FIRST_NAME,
            reset_url=SAMPLE_RESET_URL,
            ttl_hours=SAMPLE_TTL_HOURS,
        )
        target = OUT_DIR / preview["filename"]
        target.write_text(rendered.html_body, encoding="utf-8")
        print(f"  → {target}")
        print(f"      subject: {rendered.subject}")
        print(f"      ({preview['caption']})")
        print()

    # Admin signup notification (a separate render path)
    admin_rendered = render_admin_signup_notification(
        recipient_first_name="Meghana",
        requester_first_name="Aswini",
        requester_last_name="Yalavarthy",
        requester_email="aswini@cach22.ai",
        requested_at_display="Jun 16, 2026 at 04:09 PM UTC",
        reference_url=SAMPLE_RESET_URL,
    )
    admin_target = OUT_DIR / "04_admin_signup_notification.html"
    admin_target.write_text(admin_rendered.html_body, encoding="utf-8")
    print(f"  → {admin_target}")
    print(f"      subject: {admin_rendered.subject}")
    print(
        "      (Sent to every active admin when a user submits a new sign-up request via /signup.)"
    )
    print()

    print(f"Open in browser:  open {OUT_DIR}")


if __name__ == "__main__":
    main()
