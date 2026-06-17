"""Branded HTML + plaintext bodies for the password-reset family of
emails.

Three purposes share the same shell — only the headline, lead
paragraph, and CTA label differ:

* ``set_password`` — admin invited the user to the platform
* ``forgot_password`` — user requested a password reset
* ``admin_initiated`` — an administrator reset the user's password
  on their behalf

Plaintext bodies are generated alongside the HTML; some recipients
won't render the HTML version (corporate filters, accessibility
tools), so a clean text fallback matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

# Brand palette — kept in sync with the dashboard's `theme.ts`.
_GOLD = "#bb8c3f"
_GOLD_LIGHT = "#e9c46a"
_GOLD_DARK = "#8e6a2a"
_IVORY = "#faf6ee"
_INK = "#0f0a07"
_MUTED = "#5a4a35"


@dataclass(frozen=True)
class RenderedEmail:
    """A ready-to-send email payload."""

    subject: str
    html_body: str
    text_body: str


def _content_for_purpose(*, purpose: str, recipient_first_name: str) -> tuple[str, str, str, str]:
    """Return ``(subject, headline, lead, cta_label)`` for the purpose."""
    name = recipient_first_name.strip() or "there"

    if purpose == "set_password":
        return (
            "Your Hooten Young Ops Platform account is ready",
            "Welcome to the Hooten Young Ops Platform",
            (
                f"Hi {name}, a new account has been created for you on the Hooten Young "
                "Ops Platform. Click the button below to choose a password and finish "
                "setting up your account."
            ),
            "Finish account setup",
        )
    if purpose == "admin_initiated":
        return (
            "Your Hooten Young Ops Platform password has been reset",
            "Your password has been reset",
            (
                f"Hi {name}, an administrator has reset your password on the Hooten Young "
                "Ops Platform. Click the button below to choose a new one — you'll need "
                "to do this before you can sign in again."
            ),
            "Set new password",
        )
    # Default = self-service "forgot password" flow
    return (
        "Reset your Hooten Young Ops Platform password",
        "Reset your password",
        (
            f"Hi {name}, we received a request to reset the password on your Hooten Young "
            "Ops Platform account. Click the button below to choose a new one. If you "
            "didn't request this, you can safely ignore this email — your current "
            "password will keep working."
        ),
        "Reset password",
    )


def _derive_logo_url(reset_url: str) -> str:
    """Build the brand-logo URL for the email header.

    The dashboard SPA already serves ``/brand/hy-logo.png`` at the
    same origin it serves the reset-password page from, so we can
    just lift the origin off the reset URL.  That keeps the logo
    environment-aware automatically (dev → ops-dev, prod → ops)
    without adding another settings field.
    """
    parsed = urlparse(reset_url)
    return f"{parsed.scheme}://{parsed.netloc}/brand/hy-logo.png"


def render_reset_email(
    *,
    purpose: str,
    recipient_first_name: str,
    reset_url: str,
    ttl_hours: int,
) -> RenderedEmail:
    """Build the subject + HTML + plaintext bodies for a reset email.

    ``purpose`` must be one of ``set_password``, ``forgot_password``,
    ``admin_initiated``.  Anything else falls through to the
    forgot-password copy so we never fail to render.
    """
    subject, headline, lead, cta_label = _content_for_purpose(
        purpose=purpose, recipient_first_name=recipient_first_name
    )

    html_body = _HTML_TEMPLATE.format(
        subject=subject,
        headline=headline,
        lead=lead,
        cta_label=cta_label,
        reset_url=reset_url,
        ttl_hours=ttl_hours,
        logo_url=_derive_logo_url(reset_url),
        gold=_GOLD,
        gold_light=_GOLD_LIGHT,
        gold_dark=_GOLD_DARK,
        ivory=_IVORY,
        ink=_INK,
        muted=_MUTED,
    )

    text_body = (
        f"{headline}\n"
        f"{'-' * len(headline)}\n\n"
        f"{lead}\n\n"
        f"{cta_label}: {reset_url}\n\n"
        f"This link expires in {ttl_hours} hours.\n\n"
        "If you weren't expecting this email, you can ignore it.\n\n"
        "— Hooten Young"
    )

    return RenderedEmail(subject=subject, html_body=html_body, text_body=text_body)


# HTML body.  Inline styles only — Gmail, Outlook and most other
# clients strip <style> blocks, so every visual property has to live
# on the element it targets.  Layout uses tables since flexbox
# rendering in mail clients is unreliable.
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{subject}</title>
  </head>
  <body style="margin:0; padding:0; background-color:{ivory}; font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif; color:{ink};">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:{ivory};">
      <tr>
        <td align="center" style="padding: 40px 20px;">
          <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="max-width:560px; width:100%; background-color:#ffffff; border:1px solid rgba(187,140,63,0.22); border-radius:8px; overflow:hidden;">
            <!-- Gold accent strip -->
            <tr>
              <td style="height:3px; background-image: linear-gradient(to right, {gold} 0%, {gold_light} 50%, {gold} 100%); line-height:0; font-size:0;">&nbsp;</td>
            </tr>

            <!-- Brand lockup — actual logo image, centered.  Falls
                 back to alt text in clients that block remote images
                 (Gmail before "Display below" tap, Outlook, etc.). -->
            <tr>
              <td style="padding: 36px 40px 12px; text-align:center;">
                <img src="{logo_url}"
                     alt="Hooten Young"
                     width="160"
                     style="display:inline-block; height:auto; max-width:160px; width:160px; border:0; outline:none; text-decoration:none;" />
              </td>
            </tr>

            <!-- Hairline gold rule under the logo -->
            <tr>
              <td style="padding: 0 40px;" align="center">
                <div style="height:1px; width:48px; background-color:{gold}; opacity:0.7; margin: 0 auto;">&nbsp;</div>
              </td>
            </tr>

            <!-- Headline -->
            <tr>
              <td style="padding: 24px 40px 8px; text-align:left;">
                <h1 style="margin:0; font-family:'Inter','Helvetica Neue',Arial,sans-serif; font-size:24px; font-weight:700; letter-spacing:-0.015em; line-height:1.2; color:{ink};">
                  {headline}
                </h1>
              </td>
            </tr>

            <!-- Lead paragraph -->
            <tr>
              <td style="padding: 8px 40px 24px; text-align:left;">
                <p style="margin:0; font-size:14.5px; line-height:1.6; color:{muted};">
                  {lead}
                </p>
              </td>
            </tr>

            <!-- CTA button -->
            <tr>
              <td style="padding: 8px 40px 28px; text-align:left;">
                <a href="{reset_url}"
                   style="display:inline-block; padding:13px 28px; background-image: linear-gradient(135deg, {gold_light} 0%, {gold} 55%, {gold_dark} 100%); color:{ink}; font-size:12.5px; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; text-decoration:none; border-radius:4px; box-shadow: 0 2px 6px rgba(142,106,42,0.18);">
                  {cta_label}
                </a>
              </td>
            </tr>

            <!-- Plain-text fallback link + TTL -->
            <tr>
              <td style="padding: 0 40px 28px; text-align:left;">
                <p style="margin:0 0 10px; font-size:12px; line-height:1.55; color:{muted};">
                  Or paste this link into your browser:
                </p>
                <p style="margin:0; font-family:'Courier New',monospace; font-size:11.5px; line-height:1.5; color:{gold_dark}; word-break:break-all;">
                  <a href="{reset_url}" style="color:{gold_dark}; text-decoration:none;">{reset_url}</a>
                </p>
                <p style="margin:18px 0 0; font-size:12px; line-height:1.55; color:{muted};">
                  This link expires in <strong style="color:{ink};">{ttl_hours} hours</strong>. If it expires before you use it, contact your administrator for a fresh link.
                </p>
              </td>
            </tr>

            <!-- Footer hairline + signoff -->
            <tr>
              <td style="padding: 0 40px;">
                <div style="border-top:1px solid rgba(187,140,63,0.22); height:0; line-height:0; font-size:0;">&nbsp;</div>
              </td>
            </tr>
            <tr>
              <td style="padding: 18px 40px 30px; text-align:left;">
                <p style="margin:0; font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:{gold}; font-weight:700;">
                  Internal use only
                </p>
                <p style="margin:6px 0 0; font-size:11.5px; line-height:1.5; color:{muted};">
                  If you didn't expect this email, you can safely ignore it.
                </p>
              </td>
            </tr>
          </table>

          <!-- Outer copyright -->
          <p style="margin:24px 0 0; font-size:10.5px; letter-spacing:0.18em; text-transform:uppercase; color:{muted}; opacity:0.7;">
            &copy; Hooten Young American Whiskey
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
