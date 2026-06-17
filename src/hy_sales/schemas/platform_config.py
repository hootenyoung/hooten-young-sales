"""Pydantic response models for /api/platform/* endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LockedSectionsResponse(BaseModel):
    """List of section keys currently rendered as "Coming soon" on
    the landing page.  Driven by ``platform.app_config.locked_sections``.
    """

    model_config = ConfigDict(frozen=True)

    locked: list[str]
