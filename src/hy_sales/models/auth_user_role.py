"""``auth.user_roles`` — user ↔ role assignments.

One row per (user, role) assignment. Composite primary key on
``(user_id, role_id)`` enforces uniqueness — a user can't have the
same role twice. ``assigned_at`` and ``assigned_by`` carry the audit
trail at the assignment level, redundant with ``auth.audit_log`` but
much cheaper to query (no JSON scan).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from hy_sales.models.base import Base


class AuthUserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = ({"schema": "auth"},)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.roles.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # NULL for the bootstrap seed; otherwise the admin who assigned.
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id"),
        nullable=True,
    )
