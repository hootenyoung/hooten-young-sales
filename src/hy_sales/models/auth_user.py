"""``auth.users`` — user accounts.

One row per person. Email is the login identifier (normalized to
lowercase at the API boundary by a Pydantic validator; the DB CHECK
guards against direct SQL drift).

Roles are assigned via the separate ``auth.user_roles`` join table.
A user with no rows in that table effectively has zero access.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class AuthUser(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email = lower(email) AND email <> ''",
            name="users_email_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'rejected', 'disabled')",
            name="users_status_check",
        ),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        Text,
        server_default="pending",
        nullable=False,
    )

    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        server_default="false",
        nullable=False,
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # NULL for self-signup; set to the admin's id when an admin
    # creates a user directly. Self-reference is fine.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id"),
        nullable=True,
    )
