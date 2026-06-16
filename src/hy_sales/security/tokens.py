"""JWT access tokens + password-reset tokens.

JWT design
----------
Claims are intentionally minimal: ``sub`` (user UUID), ``iat`` (issued
at), and ``exp`` (expires at). Roles are NOT carried in the token —
they're loaded fresh from ``auth.user_roles`` on every authenticated
request so a revoked role takes effect immediately rather than
lingering until token expiry.

Algorithm is HS256 (HMAC-SHA256). Single-issuer setup; no need for
RS256's asymmetric verification.

Password-reset tokens
---------------------
``generate_reset_token`` returns ``(plaintext, sha256_hex)``:

* The plaintext goes into the email link sent to the user.
* The SHA-256 hex digest goes into ``auth.password_reset_tokens.token_hash``.

On reset, look up by ``hash_reset_token(plaintext_from_url)`` — never
by plaintext. This means a DB dump alone cannot be used to forge a
reset link, and timing comparisons on indexed hash columns are safe.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt


def create_access_token(
    user_id: uuid.UUID,
    *,
    secret: str,
    ttl_hours: int,
    algorithm: str = "HS256",
) -> tuple[str, int]:
    """Issue a signed JWT for ``user_id``.

    Returns ``(token, expires_in_seconds)`` so the caller can build an
    OAuth2-style response without recomputing the TTL.
    """
    now = datetime.now(UTC)
    exp = now + timedelta(hours=ttl_hours)
    payload: dict[str, str | int] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, ttl_hours * 3600


def decode_access_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
) -> uuid.UUID:
    """Verify ``token`` and return its subject as a ``UUID``.

    Raises ``jwt.InvalidTokenError`` (covers expired, malformed, bad
    signature, missing claims) — callers should translate to HTTP 401.
    """
    payload = jwt.decode(token, secret, algorithms=[algorithm])
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise jwt.InvalidTokenError("missing 'sub' claim")
    try:
        return uuid.UUID(sub)
    except ValueError as e:
        raise jwt.InvalidTokenError("'sub' claim is not a UUID") from e


def generate_reset_token() -> tuple[str, str]:
    """Create a fresh password-reset token.

    Returns ``(plaintext, sha256_hex)``:

    * ``plaintext`` — 43-character URL-safe base64 (32 bytes of entropy).
      Email this to the user; do not persist it.
    * ``sha256_hex`` — 64-character lowercase hex digest.
      Persist this in ``auth.password_reset_tokens.token_hash``.
    """
    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_reset_token(plaintext)


def hash_reset_token(plaintext: str) -> str:
    """Return the SHA-256 hex digest used to look up a reset token.

    Use this on the plaintext value pulled from the user's reset link
    to find the matching row in ``auth.password_reset_tokens``.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
