"""Cryptographic primitives for the auth layer.

* ``passwords`` — bcrypt hash / verify, compatible with the hashes
  produced by ``pgcrypto`` in the seed migration.
* ``tokens`` — JWT issue / decode, and password-reset token issue /
  hash.

Settings (secret, TTL, algorithm) are passed in by the caller rather
than imported from ``hy_sales.settings`` so these utilities stay
trivially unit-testable.
"""

from hy_sales.security.passwords import hash_password, verify_password
from hy_sales.security.tokens import (
    create_access_token,
    decode_access_token,
    generate_reset_token,
    hash_reset_token,
)

__all__ = [
    "create_access_token",
    "decode_access_token",
    "generate_reset_token",
    "hash_password",
    "hash_reset_token",
    "verify_password",
]
