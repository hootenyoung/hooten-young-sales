"""Smoke tests for the password-reset email rendering.

We don't want to assert on the entire HTML body (that's brittle), but
we do want to make sure each purpose renders the right subject + CTA
label + includes the URL + TTL.  Catches obvious template bugs without
locking the design in place.
"""

from __future__ import annotations

import pytest

from hy_sales.email.templates import render_reset_email


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
