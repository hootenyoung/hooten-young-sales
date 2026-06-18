"""Field-rep CRM endpoints.

Mounted at ``/api/field``.  Every endpoint requires the
``field_rep`` role (admins also pass via the wildcard rule in
``require_role``).

Endpoints
---------
* ``GET    /me``                          — self profile + territories
* ``PATCH  /me``                          — rep updates home address / phone
* ``GET    /today``                       — top-N priority accounts
* ``GET    /accounts``                    — paginated all-in-territory list
* ``GET    /accounts/{id}``               — account header + recent notes
* ``GET    /accounts/{id}/notes``         — full notes timeline
* ``POST   /accounts/{id}/notes``         — log a visit / call
* ``POST   /accounts/{id}/pin``           — pin for next-visit priority
* ``DELETE /accounts/{id}/pin``           — unpin

The depletions follow-up signal (``depletions_flagged``) is wired as a
constant False in V1 — every account scores on time-since-visit + pin
only.  We'll wire the real signal in iteration 1.1 once the workflow
is validated against live usage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import Integer, and_, case, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.auth.audit import audit_event
from hy_sales.auth.dependencies import CurrentUser, require_role
from hy_sales.db.session import get_session
from hy_sales.models import (
    AuthAuditLog,
    AuthUser,
    DepAccount,
    DepFact,
    FieldAccountPin,
    FieldRepProfile,
    FieldRepTerritory,
    FieldVisitNote,
)
from hy_sales.schemas.field import (
    AccountFlagCreate,
    AccountFlagHistoryItem,
    AccountFlagHistoryResponse,
    AccountFlagResponse,
    AccountsResponse,
    FieldAccountDetail,
    FieldAccountSummary,
    PinResponse,
    RepProfile,
    RepProfileSelfUpdate,
    TodayResponse,
    VisitChannel,
    VisitNote,
    VisitNoteCreate,
    VisitNotesResponse,
    VisitOutcome,
)
from hy_sales.schemas.strategic import FollowUpTrackerResponse
from hy_sales.services.depletions_strategic import get_follow_up_tracker
from hy_sales.services.field_priority import (
    DEFAULT_TODAY_LIMIT,
    compute_priority,
    is_eligible,
    next_eligible_date,
)

# Router-level dependency gates every endpoint here.  Admins pass via
# the wildcard rule baked into require_role.
router = APIRouter(
    prefix="/api/field",
    tags=["field"],
    dependencies=[Depends(require_role("field_rep"))],
)


# =====================================================================
# Internal helpers — kept small and stateless on purpose.  These shape
# the row collections the endpoint handlers use; the handlers do the
# response-model assembly.
# =====================================================================
async def _load_or_create_profile(session: AsyncSession, user_id: uuid.UUID) -> FieldRepProfile:
    """Return the rep's profile, creating an empty one if missing.

    Lazy-create so an admin who just toggled the field_rep role on an
    existing user doesn't have to also pre-seed the profile row.
    """
    profile = await session.get(FieldRepProfile, user_id)
    if profile is not None:
        return profile
    profile = FieldRepProfile(user_id=user_id)
    session.add(profile)
    await session.flush()
    return profile


async def _territory_states(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(FieldRepTerritory.state_code).where(FieldRepTerritory.user_id == user_id)
    )
    return sorted(str(r) for r in rows.scalars().all())


async def ensure_default_territory(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    home_state: str | None,
) -> bool:
    """Seed the rep's territory with their home state — but only if
    they have no territories assigned yet.

    The "you live in Florida, so you probably cover Florida" smart
    default.  Saves admins from a manual round-trip in the common
    case while still respecting any explicit assignment they've made
    (if territories already exist we leave them alone — admin owns
    the territory set once it's non-empty).

    Returns True if a row was added, False otherwise.  Idempotent.
    """
    if not home_state:
        return False
    existing = await session.scalar(
        select(func.count())
        .select_from(FieldRepTerritory)
        .where(FieldRepTerritory.user_id == user_id)
    )
    if existing:
        return False
    session.add(FieldRepTerritory(user_id=user_id, state_code=home_state))
    await session.flush()
    return True


def _profile_to_response(
    *,
    user: AuthUser,
    profile: FieldRepProfile,
    territory_states: list[str],
) -> RepProfile:
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
        territory_states=territory_states,
        is_active=profile.is_active,
    )


# =====================================================================
# /me — self profile
# =====================================================================
@router.get("/me", response_model=RepProfile)
async def get_my_profile(
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RepProfile:
    """Self-view for a rep.  Lazy-creates the profile row on first hit."""
    profile = await _load_or_create_profile(session, actor.id)
    user = await session.get(AuthUser, actor.id)
    if user is None:  # pragma: no cover — token decoded so the user exists
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    states = await _territory_states(session, actor.id)
    return _profile_to_response(user=user, profile=profile, territory_states=states)


@router.patch("/me", response_model=RepProfile)
async def update_my_profile(
    payload: RepProfileSelfUpdate,
    request: Request,
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RepProfile:
    """Rep updates their own home address + phone.

    Territory edits are admin-only and live on the admin oversight
    endpoint.  One exception: if this update fills in ``home_state``
    and the rep has no territories yet, we seed their territory with
    the home state as a smart default ("you live in Florida → you
    probably cover Florida").  Admins can still override later.
    """
    profile = await _load_or_create_profile(session, actor.id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(profile, key, value)

    audit_event(
        session,
        action="rep_self_updated_profile",
        user_id=actor.id,
        metadata={"fields_changed": sorted(data.keys())},
        request=request,
    )

    seeded = await ensure_default_territory(
        session, user_id=actor.id, home_state=profile.home_state
    )
    if seeded:
        audit_event(
            session,
            action="rep_auto_assigned_home_territory",
            user_id=actor.id,
            metadata={"state_code": profile.home_state},
            request=request,
        )

    user = await session.get(AuthUser, actor.id)
    if user is None:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    states = await _territory_states(session, actor.id)
    return _profile_to_response(user=user, profile=profile, territory_states=states)


# =====================================================================
# Depletions-metrics enrichment
# =====================================================================
# Activity buckets driven by days_since_last_shipment.  Same lo/hi
# pattern as services/depletions_strategic._FOLLOW_UP_BUCKETS so the
# bucket labels stay in lockstep across the platform.
_ACTIVITY_BUCKETS: list[tuple[str, int, int | None]] = [
    ("Active", 0, 30),
    ("1-2 mo quiet", 30, 60),
    ("2-3 mo quiet", 60, 90),
    ("3-4 mo quiet", 90, 120),
    ("Dormant 4+ mo", 120, None),
]


def _activity_bucket(days_since: int) -> str:
    for label, lo, hi in _ACTIVITY_BUCKETS:
        if days_since >= lo and (hi is None or days_since < hi):
            return label
    return _ACTIVITY_BUCKETS[-1][0]


class _DepletionsMetrics:
    """Per-account depletions snapshot: last shipment, 12-mo cases,
    distinct product count, customer-since.

    Plain data holder, populated by :func:`_load_depletions_metrics`.
    """

    __slots__ = (
        "activity_bucket",
        "customer_since",
        "days_since_last_shipment",
        "last_active_month",
        "product_count",
        "total_9l_12mo",
    )

    def __init__(self) -> None:
        self.last_active_month: date | None = None
        self.days_since_last_shipment: int | None = None
        self.activity_bucket: str | None = None
        self.total_9l_12mo: str | None = None
        self.product_count: int = 0
        self.customer_since: date | None = None


async def _load_depletions_metrics(
    session: AsyncSession, account_ids: list[int]
) -> dict[int, _DepletionsMetrics]:
    """Return a metrics snapshot per account.

    Three aggregate queries — last_active+totals, product_count,
    customer_since — keyed by account_id.  Accounts not in the
    depletions facts table get a default (zeroed) metrics object so
    the UI doesn't have to null-check.
    """
    out: dict[int, _DepletionsMetrics] = {aid: _DepletionsMetrics() for aid in account_ids}
    if not account_ids:
        return out

    today = date.today()

    # Latest period_month per account where cases were moved + the
    # rolling 12-month total.  Anchored on the latest period_month in
    # the data so a stale feed doesn't punish reps.
    latest_period: date | None = await session.scalar(select(func.max(DepFact.period_month)))
    if latest_period is None:
        return out
    window_start = date(latest_period.year - 1, latest_period.month, 1)

    last_total_stmt = (
        select(
            DepFact.account_id,
            func.max(DepFact.period_month).label("last_active"),
            func.coalesce(
                func.sum(
                    case(
                        (DepFact.period_month >= window_start, DepFact.cases_9l),
                        else_=0,
                    )
                ),
                0,
            ).label("total_9l_12mo"),
        )
        .where(DepFact.account_id.in_(account_ids))
        .where(DepFact.cases_9l != 0)
        .group_by(DepFact.account_id)
    )
    for row in (await session.execute(last_total_stmt)).all():
        m = out[row.account_id]
        m.last_active_month = row.last_active
        m.days_since_last_shipment = (today - row.last_active).days
        m.activity_bucket = _activity_bucket(m.days_since_last_shipment)
        m.total_9l_12mo = str(row.total_9l_12mo)

    # Distinct product count.
    product_count_stmt = (
        select(
            DepFact.account_id,
            func.count(func.distinct(DepFact.product_id)).label("cnt"),
        )
        .where(DepFact.account_id.in_(account_ids))
        .where(DepFact.cases_9l != 0)
        .group_by(DepFact.account_id)
    )
    for row in (await session.execute(product_count_stmt)).all():
        out[row.account_id].product_count = int(row.cnt)

    # Customer-since.
    since_stmt = (
        select(
            DepFact.account_id,
            func.min(DepFact.period_month).label("first_active"),
        )
        .where(DepFact.account_id.in_(account_ids))
        .where(DepFact.cases_9l != 0)
        .group_by(DepFact.account_id)
    )
    for row in (await session.execute(since_stmt)).all():
        out[row.account_id].customer_since = row.first_active

    return out


# =====================================================================
# /today + /accounts — listings
# =====================================================================
async def _account_rows_for_rep(
    session: AsyncSession,
    *,
    rep_id: uuid.UUID,
    territory_states: list[str],
) -> list[FieldAccountSummary]:
    """Return every account in the rep's territory, each annotated with
    last-visit info, pin status, and computed priority + eligibility.

    The bulk of the work is two parallel subqueries (last note per
    account, pin set per rep) joined onto depletions.accounts.  We then
    sort + filter + score in Python — the volumes are small enough
    (hundreds, maybe low thousands per rep) that a pure-SQL ranking
    isn't worth the complexity.
    """
    if not territory_states:
        return []

    # Latest note per account_id — DISTINCT ON keeps one row.
    latest_note_subq = (
        select(
            FieldVisitNote.account_id,
            FieldVisitNote.visit_date,
            FieldVisitNote.channel,
            FieldVisitNote.outcome,
            FieldVisitNote.note_text,
        )
        .distinct(FieldVisitNote.account_id)
        .order_by(FieldVisitNote.account_id, FieldVisitNote.visit_date.desc())
        .subquery()
    )

    pinned_ids = {
        row[0]
        for row in (
            await session.execute(
                select(FieldAccountPin.account_id).where(FieldAccountPin.rep_id == rep_id)
            )
        ).all()
    }

    stmt = (
        select(
            DepAccount.id,
            DepAccount.name,
            DepAccount.address,
            DepAccount.city,
            DepAccount.state_code,
            DepAccount.zip_code,
            DepAccount.premises_type,
            latest_note_subq.c.visit_date,
            latest_note_subq.c.channel,
            latest_note_subq.c.outcome,
            latest_note_subq.c.note_text,
        )
        .outerjoin(latest_note_subq, latest_note_subq.c.account_id == DepAccount.id)
        .where(DepAccount.state_code.in_(territory_states))
        .where(DepAccount.is_active.is_(True))
        .order_by(DepAccount.name)
    )

    raw_rows = (await session.execute(stmt)).all()
    metrics_by_id = await _load_depletions_metrics(session, [r.id for r in raw_rows])

    today = date.today()
    summaries: list[FieldAccountSummary] = []
    for row in raw_rows:
        days_since: int | None = None
        if row.visit_date is not None:
            days_since = (today - row.visit_date).days
        is_pinned = row.id in pinned_ids
        metrics = metrics_by_id.get(row.id) or _DepletionsMetrics()
        # Use the activity bucket as a soft "depletions-flagged" signal —
        # any account in cooldown beyond ~3 months is something the rep
        # should be aware of.
        is_depletions_flagged = (
            metrics.days_since_last_shipment is not None and metrics.days_since_last_shipment >= 90
        )
        score = compute_priority(
            days_since_last_visit=days_since,
            depletions_flagged=is_depletions_flagged,
            is_pinned=is_pinned,
        )
        next_elig: date | None = None
        if row.visit_date is not None and row.outcome is not None:
            next_elig = next_eligible_date(
                last_visit_date=row.visit_date,
                last_outcome=row.outcome,
            )

        excerpt = None
        if row.note_text is not None:
            excerpt = row.note_text if len(row.note_text) <= 140 else row.note_text[:137] + "…"

        summaries.append(
            FieldAccountSummary(
                account_id=row.id,
                name=row.name,
                address=row.address,
                city=row.city,
                state_code=row.state_code,
                zip_code=row.zip_code,
                premises_type=row.premises_type,
                last_visit_date=row.visit_date,
                last_outcome=row.outcome,
                last_channel=row.channel,
                last_note_excerpt=excerpt,
                days_since_last_visit=days_since,
                is_pinned=is_pinned,
                depletions_flagged=is_depletions_flagged,
                priority_score=score,
                next_eligible_date=next_elig,
                last_active_month=metrics.last_active_month,
                days_since_last_shipment=metrics.days_since_last_shipment,
                activity_bucket=metrics.activity_bucket,
                total_9l_12mo=metrics.total_9l_12mo,
                product_count=metrics.product_count,
                customer_since=metrics.customer_since,
            )
        )
    return summaries


@router.get("/today", response_model=TodayResponse)
async def get_today(
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=DEFAULT_TODAY_LIMIT, ge=1, le=50),
) -> TodayResponse:
    """Top-N priority accounts eligible to visit today.

    Eligibility filters out accounts still in cooldown from their last
    visit.  Within the eligible pool, accounts are ordered by priority
    score (highest first), then the top ``limit`` are returned.
    """
    profile = await _load_or_create_profile(session, actor.id)
    states = await _territory_states(session, actor.id)
    all_accounts = await _account_rows_for_rep(session, rep_id=actor.id, territory_states=states)

    today = date.today()
    eligible = [
        a
        for a in all_accounts
        if is_eligible(
            last_visit_date=a.last_visit_date,
            last_outcome=a.last_outcome,
            today=today,
        )
    ]
    eligible.sort(key=lambda a: a.priority_score, reverse=True)

    home_complete = bool(
        profile.home_address and profile.home_city and profile.home_state and profile.home_zip
    )

    return TodayResponse(
        accounts=eligible[:limit],
        home_address_complete=home_complete,
        territory_states=states,
    )


@router.get("/accounts", response_model=AccountsResponse)
async def list_accounts(
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AccountsResponse:
    """All accounts in the rep's territory, paginated.

    Unlike ``/today`` this does NOT filter by eligibility — the rep can
    see every account, including those still in cooldown.  Ordered by
    priority score so the most-needs-attention surface first.
    """
    states = await _territory_states(session, actor.id)
    rows = await _account_rows_for_rep(session, rep_id=actor.id, territory_states=states)
    rows.sort(key=lambda a: a.priority_score, reverse=True)
    return AccountsResponse(
        items=rows[offset : offset + limit],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


# =====================================================================
# /follow-up — depletions follow-up tracker, scoped to the rep's
# territory.  Reuses the same service the depletions section uses;
# only the state filter is rep-specific.
# =====================================================================
@router.get("/follow-up", response_model=FollowUpTrackerResponse)
async def get_field_follow_up(
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FollowUpTrackerResponse:
    """Bucketed view of the rep's territory accounts by days since
    their last depletion.  Admins with no territory get an empty
    response (every bucket has zero accounts); reps see only their
    states.
    """
    states = await _territory_states(session, actor.id)
    # No-territory short-circuit — avoid scanning the whole accounts
    # table for an admin viewer without a rep profile.
    if not states:
        data = await get_follow_up_tracker(session, state_codes=[], rep_id=actor.id)
    else:
        data = await get_follow_up_tracker(session, state_codes=states, rep_id=actor.id)
    return FollowUpTrackerResponse.model_validate(data)


# =====================================================================
# /accounts/{id} — account detail + notes
# =====================================================================
async def _ensure_account_in_territory(
    session: AsyncSession, *, rep_id: uuid.UUID, account_id: int
) -> DepAccount:
    """Load the account and verify it sits in the rep's territory.

    Admins bypass — they can see any account.  For everyone else this
    is the gate: a Florida rep can't read or write notes against a
    Texas account.
    """
    account = await session.get(DepAccount, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    actor_states = await _territory_states(session, rep_id)
    if account.state_code is None or account.state_code not in actor_states:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "out_of_territory",
                "message": "This account is not in your assigned territory.",
            },
        )
    return account


async def _notes_for_account(
    session: AsyncSession, account_id: int, *, limit: int | None = None
) -> list[VisitNote]:
    stmt = (
        select(FieldVisitNote, AuthUser.first_name, AuthUser.last_name)
        .join(AuthUser, AuthUser.id == FieldVisitNote.rep_id)
        .where(FieldVisitNote.account_id == account_id)
        .order_by(FieldVisitNote.visit_date.desc(), FieldVisitNote.created_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    out: list[VisitNote] = []
    for row in (await session.execute(stmt)).all():
        note, first, last = row
        out.append(
            VisitNote(
                id=note.id,
                account_id=note.account_id,
                rep_id=note.rep_id,
                rep_name=f"{first} {last}".strip(),
                visit_date=note.visit_date,
                channel=cast(VisitChannel, note.channel),
                outcome=cast(VisitOutcome, note.outcome),
                note_text=note.note_text,
                created_at=note.created_at,
            )
        )
    return out


@router.get("/accounts/{account_id}", response_model=FieldAccountDetail)
async def get_account_detail(
    account_id: int,
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FieldAccountDetail:
    """Account header + last 50 visit notes.

    For the full notes timeline, use ``/accounts/{id}/notes``.
    """
    # Admin sees any account; non-admin enforced to territory.
    is_admin_actor = actor.has_role("admin")
    if is_admin_actor:
        account = await session.get(DepAccount, account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    else:
        account = await _ensure_account_in_territory(
            session, rep_id=actor.id, account_id=account_id
        )

    # Build the summary row.  Last note for "last_*" fields.
    latest = (
        await session.execute(
            select(FieldVisitNote)
            .where(FieldVisitNote.account_id == account_id)
            .order_by(FieldVisitNote.visit_date.desc(), FieldVisitNote.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    is_pinned = (
        await session.scalar(
            select(
                exists().where(
                    and_(
                        FieldAccountPin.rep_id == actor.id,
                        FieldAccountPin.account_id == account_id,
                    )
                )
            )
        )
        or False
    )

    today = date.today()
    days_since = (today - latest.visit_date).days if latest is not None else None

    metrics_by_id = await _load_depletions_metrics(session, [account.id])
    metrics = metrics_by_id.get(account.id) or _DepletionsMetrics()
    is_depletions_flagged = (
        metrics.days_since_last_shipment is not None and metrics.days_since_last_shipment >= 90
    )
    score = compute_priority(
        days_since_last_visit=days_since,
        depletions_flagged=is_depletions_flagged,
        is_pinned=is_pinned,
    )
    next_elig = (
        next_eligible_date(last_visit_date=latest.visit_date, last_outcome=latest.outcome)
        if latest is not None
        else None
    )
    excerpt = None
    if latest is not None:
        excerpt = latest.note_text if len(latest.note_text) <= 140 else latest.note_text[:137] + "…"

    summary = FieldAccountSummary(
        account_id=account.id,
        name=account.name,
        address=account.address,
        city=account.city,
        state_code=account.state_code,
        zip_code=account.zip_code,
        premises_type=account.premises_type,
        last_visit_date=latest.visit_date if latest is not None else None,
        last_outcome=cast(VisitOutcome, latest.outcome) if latest is not None else None,
        last_channel=cast(VisitChannel, latest.channel) if latest is not None else None,
        last_note_excerpt=excerpt,
        days_since_last_visit=days_since,
        is_pinned=is_pinned,
        depletions_flagged=is_depletions_flagged,
        priority_score=score,
        next_eligible_date=next_elig,
        last_active_month=metrics.last_active_month,
        days_since_last_shipment=metrics.days_since_last_shipment,
        activity_bucket=metrics.activity_bucket,
        total_9l_12mo=metrics.total_9l_12mo,
        product_count=metrics.product_count,
        customer_since=metrics.customer_since,
    )

    notes = await _notes_for_account(session, account_id, limit=50)
    return FieldAccountDetail(summary=summary, notes=notes)


@router.get("/accounts/{account_id}/notes", response_model=VisitNotesResponse)
async def list_notes(
    account_id: int,
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisitNotesResponse:
    """Full notes timeline for an account."""
    if not actor.has_role("admin"):
        await _ensure_account_in_territory(session, rep_id=actor.id, account_id=account_id)
    elif await session.get(DepAccount, account_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    notes = await _notes_for_account(session, account_id)
    return VisitNotesResponse(items=notes)


@router.post(
    "/accounts/{account_id}/notes",
    response_model=VisitNote,
    status_code=status.HTTP_201_CREATED,
)
async def create_note(
    account_id: int,
    payload: VisitNoteCreate,
    request: Request,
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisitNote:
    """Log a new visit / call for the account."""
    if not actor.has_role("admin"):
        await _ensure_account_in_territory(session, rep_id=actor.id, account_id=account_id)
    elif await session.get(DepAccount, account_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    note = FieldVisitNote(
        account_id=account_id,
        rep_id=actor.id,
        visit_date=payload.visit_date,
        channel=payload.channel,
        outcome=payload.outcome,
        note_text=payload.note_text,
    )
    session.add(note)
    await session.flush()

    audit_event(
        session,
        action="rep_visit_logged",
        user_id=actor.id,
        metadata={
            "account_id": account_id,
            "channel": payload.channel,
            "outcome": payload.outcome,
            "visit_date": payload.visit_date.isoformat(),
        },
        request=request,
    )
    user = await session.get(AuthUser, actor.id)
    rep_name = f"{user.first_name} {user.last_name}".strip() if user else ""
    return VisitNote(
        id=note.id,
        account_id=note.account_id,
        rep_id=note.rep_id,
        rep_name=rep_name,
        visit_date=note.visit_date,
        channel=cast(VisitChannel, note.channel),
        outcome=cast(VisitOutcome, note.outcome),
        note_text=note.note_text,
        created_at=note.created_at,
    )


# =====================================================================
# Pins
# =====================================================================
@router.post("/accounts/{account_id}/pin", response_model=PinResponse)
async def pin_account(
    account_id: int,
    request: Request,
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PinResponse:
    """Pin an account for next-visit priority.  Idempotent."""
    if not actor.has_role("admin"):
        await _ensure_account_in_territory(session, rep_id=actor.id, account_id=account_id)

    existing = await session.get(FieldAccountPin, (actor.id, account_id))
    if existing is None:
        session.add(FieldAccountPin(rep_id=actor.id, account_id=account_id))
        audit_event(
            session,
            action="rep_pinned_account",
            user_id=actor.id,
            metadata={"account_id": account_id},
            request=request,
        )
    return PinResponse(account_id=account_id, is_pinned=True)


@router.delete("/accounts/{account_id}/pin", response_model=PinResponse)
async def unpin_account(
    account_id: int,
    request: Request,
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PinResponse:
    """Remove the pin.  Idempotent."""
    await session.execute(
        delete(FieldAccountPin)
        .where(FieldAccountPin.rep_id == actor.id)
        .where(FieldAccountPin.account_id == account_id)
    )
    audit_event(
        session,
        action="rep_unpinned_account",
        user_id=actor.id,
        metadata={"account_id": account_id},
        request=request,
    )
    return PinResponse(account_id=account_id, is_pinned=False)


# =====================================================================
# Flag for admin review
# =====================================================================
@router.post(
    "/accounts/{account_id}/flag",
    response_model=AccountFlagResponse,
    status_code=status.HTTP_201_CREATED,
)
async def flag_account_for_review(
    account_id: int,
    payload: AccountFlagCreate,
    request: Request,
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccountFlagResponse:
    """Flag an account for admin review with a free-form reason.

    Used by reps when the account has an issue that doesn't fit the
    structured visit outcomes — permanent closure, ownership change,
    distribution misroute, data correction needed.  The flag is
    written to the auth audit log so admins can review via existing
    audit tooling; no new queryable surface is added here.

    A rep can only flag accounts in their territory; admins can flag
    any account (matches the pin/note endpoints' authorization).
    """
    if not actor.has_role("admin"):
        await _ensure_account_in_territory(session, rep_id=actor.id, account_id=account_id)
    elif await session.get(DepAccount, account_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    flagged_at = datetime.now(UTC)
    audit_event(
        session,
        action="account_flagged_for_review",
        user_id=actor.id,
        metadata={
            "account_id": account_id,
            "reason": payload.reason,
            "flagged_at": flagged_at.isoformat(),
        },
        request=request,
    )
    return AccountFlagResponse(account_id=account_id, flagged_at=flagged_at)


@router.get(
    "/accounts/{account_id}/flags",
    response_model=AccountFlagHistoryResponse,
)
async def list_account_flags(
    account_id: int,
    actor: Annotated[CurrentUser, Depends(require_role("field_rep"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccountFlagHistoryResponse:
    """List every prior flag on this account, newest first.

    Flags are stored as ``auth.audit_log`` rows with
    ``action='account_flagged_for_review'`` and the account_id in the
    metadata JSON.  We left-join ``auth.users`` to surface the rep's
    display name so the timeline reads naturally; missing users
    (e.g. deactivated reps) render as "Unknown rep" on the client.

    Authorization matches the POST /flag endpoint: reps see flags
    on accounts in their territory; admins see any account.
    """
    if not actor.has_role("admin"):
        await _ensure_account_in_territory(session, rep_id=actor.id, account_id=account_id)
    elif await session.get(DepAccount, account_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Postgres JSONB cast — metadata->>'account_id' returns text, so
    # cast to int before comparing.  Index on
    # (action, (metadata->>'account_id')) would optimize this but
    # flags are sparse enough that a plain scan stays cheap.
    stmt = (
        select(
            AuthAuditLog.id,
            AuthAuditLog.user_id,
            AuthAuditLog.metadata_,
            AuthAuditLog.occurred_at,
            AuthUser.first_name,
            AuthUser.last_name,
        )
        .outerjoin(AuthUser, AuthUser.id == AuthAuditLog.user_id)
        .where(AuthAuditLog.action == "account_flagged_for_review")
        .where(AuthAuditLog.metadata_["account_id"].astext.cast(Integer) == account_id)
        .order_by(AuthAuditLog.occurred_at.desc())
    )
    rows = (await session.execute(stmt)).all()

    items: list[AccountFlagHistoryItem] = []
    for row in rows:
        name_parts = [row.first_name or "", row.last_name or ""]
        rep_name = " ".join(part for part in name_parts if part).strip() or "Unknown rep"
        reason = str(row.metadata_.get("reason", ""))
        items.append(
            AccountFlagHistoryItem(
                id=row.id,
                rep_id=row.user_id,
                rep_name=rep_name,
                reason=reason,
                flagged_at=row.occurred_at,
            )
        )
    return AccountFlagHistoryResponse(items=items)
