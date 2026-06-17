"""Pydantic request and response models for the feedback endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Constrained to the same set the DB CHECK constraint enforces.  Keep
# in sync with db/migrations/007_auth_feedback.sql.
FeedbackCategory = Literal["idea", "bug", "praise", "other"]


class FeedbackSubmitRequest(BaseModel):
    """Body of POST /api/feedback."""

    category: FeedbackCategory
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    page_path: Annotated[str | None, Field(default=None, max_length=200)]
    allow_followup: bool = True


class FeedbackSubmitResponse(BaseModel):
    """Result of a successful feedback submission.

    ``email_dispatched`` is True when at least one recipient email was
    accepted by SendGrid; False if SendGrid wasn't configured or every
    recipient failed.  The DB row is always written either way — that
    boolean is purely diagnostic for the client.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    created_at: datetime
    email_dispatched: bool
