"""Admin oversight endpoints for the field-rep CRM.

Mounted at ``/api/admin/field``.  Every endpoint requires the
``admin`` role.  This is where admins see the whole picture across
every rep — the roster, individual rep deep-dives, territory edits,
and a chronological activity feed of all visit notes.

Endpoints
---------
* ``GET   /reps``                      — roster of all reps
* ``GET   /reps/{user_id}``            — single rep detail (profile + recent notes)
* ``PATCH /reps/{user_id}``            — admin updates profile + territories
* ``GET   /activity``                  — paginated cross-rep activity feed
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.api.field import ensure_default_territory
from hy_sales.auth.audit import audit_event
from hy_sales.auth.dependencies import CurrentUser, require_role
from hy_sales.db.session import get_session
from hy_sales.models import (
    AuthRole,
    AuthUser,
    AuthUserRole,
    DepAccount,
    FieldRepProfile,
    FieldRepTerritory,
    FieldVisitNote,
)
from hy_sales.schemas.field import (
    AdminActivityResponse,
    AdminActivityRow,
    AdminRepRow,
    AdminRepsResponse,
    RepProfile,
    RepProfileAdminUpdate,
    VisitChannel,
    VisitOutcome,
)

require_admin = require_role("admin")

router = APIRouter(
    prefix="/api/admin/field",
    tags=["admin", "field"],
    dependencies=[Depends(require_admin)],
)


_FIELD_REP_ROLE = "field_rep"
_RECENT_NOTE_EXCERPT_LEN = 140


# =====================================================================
# Helpers
# =====================================================================
async def _territory_states(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(FieldRepTerritory.state_code).where(FieldRepTerritory.user_id == user_id)
    )
    return sorted(str(r) for r in rows.scalars().all())


async def _replace_territories(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    state_codes: list[str],
) -> list[str]:
    """Replace a rep's territory set with the given states.

    Uppercases + de-dupes the input so the DB stays clean even if the
    caller sent mixed-case state codes.
    """
    normalized = sorted({s.strip().upper() for s in state_codes if s.strip()})
    await session.execute(delete(FieldRepTerritory).where(FieldRepTerritory.user_id == user_id))
    for code in normalized:
        if len(code) != 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid_state_code",
                    "message": f"State codes must be 2 letters; got {code!r}.",
                },
            )
        session.add(FieldRepTerritory(user_id=user_id, state_code=code))
    await session.flush()
    return normalized


def _excerpt(text: str) -> str:
    if len(text) <= _RECENT_NOTE_EXCERPT_LEN:
        return text
    return text[: _RECENT_NOTE_EXCERPT_LEN - 1] + "…"


async def _load_rep_or_404(session: AsyncSession, user_id: uuid.UUID) -> AuthUser:
    user = await session.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Verify the user has the field_rep role.  Admin-only users without
    # the role aren't reps — return 404 so we don't silently return an
    # empty profile.
    has_role = await session.scalar(
        select(func.count())
        .select_from(AuthUserRole)
        .join(AuthRole, AuthRole.id == AuthUserRole.role_id)
        .where(AuthUserRole.user_id == user_id)
        .where(AuthRole.name == _FIELD_REP_ROLE)
    )
    if not has_role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_a_field_rep",
                "message": "This user is not assigned the field_rep role.",
            },
        )
    return user


# =====================================================================
# Roster
# =====================================================================
@router.get("/reps", response_model=AdminRepsResponse)
async def list_reps(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminRepsResponse:
    """List every user with the ``field_rep`` role + their last 30-day
    activity counters.
    """
    # Reps = users with the field_rep role.  LEFT OUTER JOIN profile so
    # a freshly-granted rep with no profile row yet still shows up.
    rep_users_stmt = (
        select(AuthUser, FieldRepProfile)
        .join(AuthUserRole, AuthUserRole.user_id == AuthUser.id)
        .join(AuthRole, AuthRole.id == AuthUserRole.role_id)
        .outerjoin(FieldRepProfile, FieldRepProfile.user_id == AuthUser.id)
        .where(AuthRole.name == _FIELD_REP_ROLE)
        .order_by(AuthUser.first_name, AuthUser.last_name)
    )
    rep_rows = (await session.execute(rep_users_stmt)).all()

    # 30-day visit counts per rep.  Single GROUP BY query.
    since = datetime.now(UTC) - timedelta(days=30)
    counts_stmt = (
        select(
            FieldVisitNote.rep_id,
            func.count(FieldVisitNote.id).label("cnt"),
            func.max(FieldVisitNote.created_at).label("last_at"),
        )
        .where(FieldVisitNote.created_at >= since)
        .group_by(FieldVisitNote.rep_id)
    )
    counts: dict[uuid.UUID, tuple[int, datetime | None]] = {}
    for crow in (await session.execute(counts_stmt)).all():
        counts[crow.rep_id] = (crow.cnt, crow.last_at)

    # Territories per rep.  One round trip total.
    terr_stmt = select(FieldRepTerritory.user_id, FieldRepTerritory.state_code).order_by(
        FieldRepTerritory.user_id, FieldRepTerritory.state_code
    )
    territories: dict[uuid.UUID, list[str]] = {}
    for trow in (await session.execute(terr_stmt)).all():
        territories.setdefault(trow.user_id, []).append(trow.state_code)

    items: list[AdminRepRow] = []
    for user, profile in rep_rows:
        cnt, last_at = counts.get(user.id, (0, None))
        items.append(
            AdminRepRow(
                user_id=user.id,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                territory_states=territories.get(user.id, []),
                is_active=profile.is_active if profile is not None else True,
                visit_count_30d=cnt,
                last_visit_at=last_at,
            )
        )
    return AdminRepsResponse(items=items)


# =====================================================================
# Single rep
# =====================================================================
@router.get("/reps/{user_id}", response_model=RepProfile)
async def get_rep(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RepProfile:
    user = await _load_rep_or_404(session, user_id)
    profile = await session.get(FieldRepProfile, user_id)
    if profile is None:
        # Materialize a default so the response is well-shaped even
        # before the rep has saved any details.
        profile = FieldRepProfile(user_id=user_id)
        session.add(profile)
        await session.flush()
    states = await _territory_states(session, user_id)
    return RepProfile(
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        home_address=profile.home_address,
        home_city=profile.home_city,
        home_state=profile.home_state,
        home_zip=profile.home_zip,
        phone=profile.phone,
        territory_states=states,
        is_active=profile.is_active,
    )


@router.patch("/reps/{user_id}", response_model=RepProfile)
async def update_rep(
    user_id: uuid.UUID,
    payload: RepProfileAdminUpdate,
    request: Request,
    actor: Annotated[CurrentUser, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RepProfile:
    """Admin updates a rep's profile + territories.

    Profile and territories are independent — only ``territory_states``
    rewrites the territory set; passing the other fields without it
    leaves territory unchanged.
    """
    user = await _load_rep_or_404(session, user_id)
    profile = await session.get(FieldRepProfile, user_id)
    if profile is None:
        profile = FieldRepProfile(user_id=user_id)
        session.add(profile)
        await session.flush()

    data = payload.model_dump(exclude_unset=True)
    new_states = data.pop("territory_states", None)
    changed_fields = sorted(data.keys())
    for key, value in data.items():
        setattr(profile, key, value)

    seeded_default = False
    if new_states is not None:
        await _replace_territories(session, user_id=user_id, state_codes=new_states)
    else:
        # Admin didn't explicitly set territory_states this round.  If
        # the rep currently has no territories AND a home_state is set,
        # seed the default (their home state) so the rep doesn't end up
        # with a profile but no working surface.
        seeded_default = await ensure_default_territory(
            session, user_id=user_id, home_state=profile.home_state
        )

    audit_event(
        session,
        action="admin_updated_field_rep",
        user_id=user_id,
        metadata={
            "actor_id": str(actor.id),
            "fields_changed": changed_fields,
            "territories_replaced": new_states is not None,
            "auto_seeded_home_territory": seeded_default,
        },
        request=request,
    )

    states = await _territory_states(session, user_id)
    return RepProfile(
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        home_address=profile.home_address,
        home_city=profile.home_city,
        home_state=profile.home_state,
        home_zip=profile.home_zip,
        phone=profile.phone,
        territory_states=states,
        is_active=profile.is_active,
    )


# =====================================================================
# Activity feed
# =====================================================================
@router.get("/activity", response_model=AdminActivityResponse)
async def list_activity(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminActivityResponse:
    """Cross-rep activity feed — every visit note, newest first."""
    total = await session.scalar(select(func.count()).select_from(FieldVisitNote)) or 0

    stmt = (
        select(
            FieldVisitNote,
            AuthUser.first_name,
            AuthUser.last_name,
            DepAccount.name.label("account_name"),
            DepAccount.state_code.label("account_state"),
        )
        .join(AuthUser, AuthUser.id == FieldVisitNote.rep_id)
        .join(DepAccount, DepAccount.id == FieldVisitNote.account_id)
        .order_by(FieldVisitNote.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items: list[AdminActivityRow] = []
    for row in (await session.execute(stmt)).all():
        note, first, last, acct_name, acct_state = row
        items.append(
            AdminActivityRow(
                note_id=note.id,
                rep_id=note.rep_id,
                rep_name=f"{first} {last}".strip(),
                account_id=note.account_id,
                account_name=acct_name,
                account_state=acct_state,
                visit_date=note.visit_date,
                channel=cast(VisitChannel, note.channel),
                outcome=cast(VisitOutcome, note.outcome),
                note_excerpt=_excerpt(note.note_text),
                created_at=note.created_at,
            )
        )
    return AdminActivityResponse(items=items, total=total, limit=limit, offset=offset)
