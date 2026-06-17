"""Read-only endpoints over the ``platform.app_config`` table.

For now this serves one read — the list of section keys marked
"Coming soon" — but the file is structured so additional cross-domain
config reads can land here cleanly as the platform grows (feature
flags, surface toggles, etc.).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.auth.dependencies import CurrentUser, get_current_user
from hy_sales.db.session import get_session
from hy_sales.models import PlatformAppConfig
from hy_sales.schemas.platform_config import LockedSectionsResponse

router = APIRouter(prefix="/api/platform", tags=["platform"])


_LOCKED_SECTIONS_KEY = "locked_sections"


@router.get("/locked-sections", response_model=LockedSectionsResponse)
async def get_locked_sections(
    _: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LockedSectionsResponse:
    """Return the section keys currently marked "Coming soon".

    Driven entirely by ``platform.app_config.locked_sections`` so the
    list can be changed at runtime via a single UPDATE statement —
    no redeploy.  Returns an empty list when the row is missing,
    is_active=False, or has no parseable entries.
    """
    keys = await _load_csv_value(session, _LOCKED_SECTIONS_KEY)
    return LockedSectionsResponse(locked=keys)


async def _load_csv_value(session: AsyncSession, key: str) -> list[str]:
    """Read a comma-separated TEXT config row and return its tokens.

    Generic helper kept private to this module.  If a second endpoint
    here grows the same pattern, lift it into a shared place.
    """
    row = (
        await session.execute(
            select(PlatformAppConfig).where(
                PlatformAppConfig.key == key,
                PlatformAppConfig.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if row is None:
        return []

    return [token.strip() for token in row.value.split(",") if token.strip()]
