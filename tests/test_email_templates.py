"""Smoke tests for the password-reset email rendering.

We don't want to assert on the entire HTML body (that's brittle), but
we do want to make sure each purpose renders the right subject + CTA
label + includes the URL + TTL.  Catches obvious template bugs without
locking the design in place.
"""

from __future__ import annotations

import pytest

from hy_sales.email.templates import (
    render_admin_signup_notification,
    render_reset_email,
)


@pytest.mark.parametrize(
    ("purpose", "expected_subject", "expected_cta"),
    [
        (
            "set_password",
            "Your Hooten Young Ops Platform account is ready",
            "Finish account setup",
        ),
        (
            "forgot_password",
            "Reset your Hooten Young Ops Platform password",
            "Reset password",
        ),
        (
            "admin_initiated",
            "Your Hooten Young Ops Platform password has been reset",
            "Set new password",
        ),
        # Unknown purpose falls back to the forgot-password copy so we
        # never fail to render.
        (
            "something_unknown",
            "Reset your Hooten Young Ops Platform password",
            "Reset password",
        ),
    ],
)
def test_subject_and_cta_per_purpose(
    purpose: str, expected_subject: str, expected_cta: str
) -> None:
    rendered = render_reset_email(
        purpose=purpose,
        recipient_first_name="Prasad",
        reset_url="https://example.test/reset?token=abc",
        ttl_hours=24,
    )
    assert rendered.subject == expected_subject
    assert expected_cta in rendered.html_body
    assert expected_cta in rendered.text_body


def test_reset_url_and_ttl_are_inlined() -> None:
    rendered = render_reset_email(
        purpose="forgot_password",
        recipient_first_name="Prasad",
        reset_url="https://example.test/reset?token=xyz",
        ttl_hours=24,
    )
    assert "https://example.test/reset?token=xyz" in rendered.html_body
    assert "https://example.test/reset?token=xyz" in rendered.text_body
    assert "24 hours" in rendered.html_body
    assert "24 hours" in rendered.text_body


def test_recipient_first_name_appears_in_lead() -> None:
    rendered = render_reset_email(
        purpose="set_password",
        recipient_first_name="Prasad",
        reset_url="https://example.test/reset?token=abc",
        ttl_hours=24,
    )
    # Lead paragraph greets the user by first name in both formats.
    assert "Hi Prasad" in rendered.html_body
    assert "Hi Prasad" in rendered.text_body


def test_missing_first_name_falls_back_gracefully() -> None:
    rendered = render_reset_email(
        purpose="forgot_password",
        recipient_first_name="   ",  # whitespace-only, common edge case
        reset_url="https://example.test/reset?token=abc",
        ttl_hours=24,
    )
    assert "Hi there" in rendered.html_body
    assert "Hi there" in rendered.text_body


def test_logo_url_is_derived_from_reset_url_origin() -> None:
    """The logo URL must follow the reset URL's origin so dev emails
    use the dev frontend's logo and prod emails use prod's — without
    needing a separate setting.
    """
    rendered_dev = render_reset_email(
        purpose="set_password",
        recipient_first_name="Prasad",
        reset_url="https://ops-dev.hootenyoung.com/auth/reset-password?token=abc",
        ttl_hours=24,
    )
    assert "https://ops-dev.hootenyoung.com/brand/hy-logo.png" in rendered_dev.html_body

    rendered_prod = render_reset_email(
        purpose="set_password",
        recipient_first_name="Prasad",
        reset_url="https://ops.hootenyoung.com/auth/reset-password?token=xyz",
        ttl_hours=24,
    )
    assert "https://ops.hootenyoung.com/brand/hy-logo.png" in rendered_prod.html_body


# ---------------------------------------------------------------------
# Admin signup notification
# ---------------------------------------------------------------------


def test_admin_signup_notification_includes_requester_details() -> None:
    rendered = render_admin_signup_notification(
        recipient_first_name="Meghana",
        requester_first_name="Aswini",
        requester_last_name="Yalavarthy",
        requester_email="aswini@example.test",
        requested_at_display="Jun 16, 2026 at 04:09 PM UTC",
        reference_url="https://ops-dev.hootenyoung.com/auth/reset-password",
    )

    assert rendered.subject == "New sign-up request — review needed"
    # Recipient greeting
    assert "Hi Meghana" in rendered.html_body
    assert "Hi Meghana" in rendered.text_body
    # Requester details surface in both bodies
    assert "Aswini Yalavarthy" in rendered.html_body
    assert "Aswini Yalavarthy" in rendered.text_body
    assert "aswini@example.test" in rendered.html_body
    assert "aswini@example.test" in rendered.text_body
    assert "Jun 16, 2026 at 04:09 PM UTC" in rendered.html_body
    assert "Jun 16, 2026 at 04:09 PM UTC" in rendered.text_body


def test_admin_signup_notification_review_url_is_environment_aware() -> None:
    """The 'Review request' CTA must point at the same environment's
    dashboard as the reference URL — admins reading the dev email get
    sent to the dev Pending Approvals tab, not prod's."""
    rendered_dev = render_admin_signup_notification(
        recipient_first_name="Prasad",
        requester_first_name="New",
        requester_last_name="User",
        requester_email="new@example.test",
        requested_at_display="Jun 16, 2026",
        reference_url="https://ops-dev.hootenyoung.com/auth/reset-password",
    )
    assert "https://ops-dev.hootenyoung.com/admin/pending" in rendered_dev.html_body
    assert "https://ops-dev.hootenyoung.com/admin/pending" in rendered_dev.text_body

    rendered_prod = render_admin_signup_notification(
        recipient_first_name="Prasad",
        requester_first_name="New",
        requester_last_name="User",
        requester_email="new@example.test",
        requested_at_display="Jun 16, 2026",
        reference_url="https://ops.hootenyoung.com/auth/reset-password",
    )
    assert "https://ops.hootenyoung.com/admin/pending" in rendered_prod.html_body
    assert "https://ops.hootenyoung.com/admin/pending" in rendered_prod.text_body


def test_admin_signup_notification_falls_back_for_missing_recipient_name() -> None:
    rendered = render_admin_signup_notification(
        recipient_first_name="",
        requester_first_name="Aswini",
        requester_last_name="",
        requester_email="aswini@example.test",
        requested_at_display="Just now",
        reference_url="https://ops.hootenyoung.com/auth/reset-password",
    )
    assert "Hi there" in rendered.html_body
    assert "Hi there" in rendered.text_body
    # Requester name strips and still surfaces gracefully.
    assert "Aswini" in rendered.html_body
