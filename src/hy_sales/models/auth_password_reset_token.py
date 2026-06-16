"""``auth.password_reset_tokens`` — one-time password set/reset tokens.

Powers two flows that share the same mechanism:

* ``forgot_password`` — user clicks "forgot password" and gets a link.
* ``set_password``    — admin creates an account; user gets a link
  to set their initial password.

Storage: only the SHA-256 hex digest of the plaintext token is stored.
The plaintext only ever lives in the email sent to the user.

Lifecycle: single-use. ``used_at IS NOT NULL`` means consumed and
cannot be reused. Rows are kept after consumption for audit.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class AuthPasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('forgot_password', 'set_password')",
            name="password_reset_tokens_purpose_check",
        ),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # SHA-256 hex digest of the plaintext token (64 chars).
    # Lookup: WHERE token_hash = sha256_hex($1)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    purpose: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # NULL until consumed. Kept post-consumption for audit.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Forensics: IP that triggered the request (forgot_password) or
    # admin user-agent context (set_password).
    requested_by_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
