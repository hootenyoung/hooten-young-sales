"""Password hashing + verification using bcrypt.

bcrypt cost factor is 12 — the same value used by ``pgcrypto.crypt()``
in the seed migration, so hashes produced by either side are
verifiable by the other.

bcrypt truncates passwords beyond 72 bytes; ``schemas.auth.PasswordStr``
limits inputs to 128 characters at the API boundary so most users
won't hit it, but be aware that two distinct 100-byte passwords
sharing their first 72 bytes will compare equal. This is a known
bcrypt limitation, not a bug in this layer.
"""

from __future__ import annotations

import bcrypt

# Cost factor. Each +1 doubles hash/verify time. 12 ≈ 250 ms on
# modern hardware — slow enough to thwart offline attacks, fast
# enough that login latency is imperceptible.
_BCRYPT_ROUNDS = 12


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash of ``plaintext``.

    The output is a 60-character ASCII string starting with ``$2b$``.
    Safe to store directly in ``auth.users.password_hash`` (Text).
    """
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    digest = bcrypt.hashpw(plaintext.encode("utf-8"), salt)
    return digest.decode("ascii")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True iff ``plaintext`` matches the stored bcrypt hash.

    Returns False — never raises — for malformed hashes or empty
    inputs. Callers can branch on the bool without try/except.

    Compatible with hashes produced by ``pgcrypto.crypt('...', gen_salt('bf', 12))``
    because they share the bcrypt wire format (``$2a$`` / ``$2b$``).
    """
    if not hashed or not plaintext:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        # Malformed hash — treat as "no match" rather than crashing
        # the login endpoint.
        return False
