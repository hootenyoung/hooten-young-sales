"""Pydantic request and response models for the field-rep CRM."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Mirrors the DB CHECK constraints in db/migrations/009_field_schema.sql.
VisitChannel = Literal["visit", "call"]
VisitOutcome = Literal["ordered", "follow_up_needed", "no_response", "declined", "info_only"]


# =====================================================================
# Rep profile
# =====================================================================
class RepProfile(BaseModel):
    """A field rep's profile + territories.

    Returned by ``GET /api/field/me`` (self-view for a rep) and from
    the admin oversight endpoints.  Territories are denormalised into
    a list of state codes for client convenience.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    email: str
    first_name: str
    last_name: str

    home_address: str | None
    home_city: str | None
    home_state: str | None
    home_zip: str | None
    phone: str | None

    territory_states: list[str]
    is_active: bool


class RepProfileSelfUpdate(BaseModel):
    """Body of ``PATCH /api/field/me``.

    What a rep is allowed to change about themselves: home address +
    phone.  Territory changes are admin-only.
    """

    home_address: Annotated[str | None, Field(default=None, max_length=200)]
    home_city: Annotated[str | None, Field(default=None, max_length=100)]
    home_state: Annotated[str | None, Field(default=None, max_length=2, min_length=2)]
    home_zip: Annotated[str | None, Field(default=None, max_length=10)]
    phone: Annotated[str | None, Field(default=None, max_length=30)]


class RepProfileAdminUpdate(BaseModel):
    """Body of ``PATCH /api/admin/field/reps/{user_id}``.

    The admin-side superset: same home/phone fields as the rep's own
    update PLUS the territory state list.
    """

    home_address: Annotated[str | None, Field(default=None, max_length=200)]
    home_city: Annotated[str | None, Field(default=None, max_length=100)]
    home_state: Annotated[str | None, Field(default=None, max_length=2, min_length=2)]
    home_zip: Annotated[str | None, Field(default=None, max_length=10)]
    phone: Annotated[str | None, Field(default=None, max_length=30)]
    territory_states: Annotated[list[str] | None, Field(default=None)]
    is_active: bool | None = None


# =====================================================================
# Today's list + account browsing
# =====================================================================
class FieldAccountSummary(BaseModel):
    """One row in either the Today's-list timeline or the All-accounts
    grid.  Carries enough info for the card render without a second
    request — basic account header + visit-note signals + depletions
    metrics (cases moved, product count, last active month) so the rep
    can see retail performance at a glance.
    """

    model_config = ConfigDict(frozen=True)

    account_id: int
    name: str
    address: str | None
    city: str | None
    state_code: str | None
    zip_code: str | None
    premises_type: str | None

    last_visit_date: date | None
    last_outcome: VisitOutcome | None
    last_channel: VisitChannel | None
    last_note_excerpt: str | None

    days_since_last_visit: int | None
    is_pinned: bool
    depletions_flagged: bool
    priority_score: int

    next_eligible_date: date | None

    # Depletions metrics — sourced from depletions.facts.  Null when
    # the account has no shipments in the data feed (a new prospect
    # or a quiet account beyond the dataset window).
    last_active_month: date | None
    days_since_last_shipment: int | None
    activity_bucket: str | None
    total_9l_12mo: str | None  # serialized Decimal — UI parses
    product_count: int
    customer_since: date | None


class TodayResponse(BaseModel):
    """Result of ``GET /api/field/today``."""

    model_config = ConfigDict(frozen=True)

    accounts: list[FieldAccountSummary]
    home_address_complete: bool
    territory_states: list[str]


class AccountsResponse(BaseModel):
    """Result of ``GET /api/field/accounts``."""

    model_config = ConfigDict(frozen=True)

    items: list[FieldAccountSummary]
    total: int
    limit: int
    offset: int


# =====================================================================
# Visit notes
# =====================================================================
class VisitNote(BaseModel):
    """One row in the visit-notes timeline."""

    model_config = ConfigDict(frozen=True)

    id: int
    account_id: int
    rep_id: uuid.UUID
    rep_name: str

    visit_date: date
    channel: VisitChannel
    outcome: VisitOutcome
    note_text: str

    created_at: datetime


class VisitNoteCreate(BaseModel):
    """Body of ``POST /api/field/accounts/{id}/notes``."""

    visit_date: date
    channel: VisitChannel
    outcome: VisitOutcome
    note_text: Annotated[str, Field(min_length=1, max_length=10_000)]


class VisitNotesResponse(BaseModel):
    """Result of ``GET /api/field/accounts/{id}/notes``."""

    model_config = ConfigDict(frozen=True)

    items: list[VisitNote]


# =====================================================================
# Flag for admin review
# =====================================================================
class AccountFlagCreate(BaseModel):
    """Body of ``POST /api/field/accounts/{id}/flag``.

    Rep-driven escape valve for account-level issues that don't fit
    the structured visit outcomes (permanent closure, ownership
    change, distribution misroute, etc.). The reason is stored in
    the auth audit log under ``action=account_flagged_for_review``
    so admins can review and act on the account record itself —
    marking inactive, transferring ownership, or correcting fields.
    """

    reason: Annotated[str, Field(min_length=1, max_length=2_000)]


class AccountFlagResponse(BaseModel):
    """Result of ``POST /api/field/accounts/{id}/flag`` — acknowledges
    receipt of the flag.  The flag itself lives in the audit log, not
    in a queryable surface (admins receive it via existing audit
    tooling).
    """

    model_config = ConfigDict(frozen=True)

    account_id: int
    flagged_at: datetime


class AccountFlagHistoryItem(BaseModel):
    """Single past flag on an account.  Read straight off the audit log
    where flags are written; status is always ``open`` for now since
    we haven't built the admin resolution flow yet.
    """

    model_config = ConfigDict(frozen=True)

    id: int  # audit_log row id; stable per-flag identifier
    rep_id: uuid.UUID | None
    rep_name: str
    reason: str
    flagged_at: datetime


class AccountFlagHistoryResponse(BaseModel):
    """Result of ``GET /api/field/accounts/{id}/flags`` — every prior
    flag on this account ordered newest-first.  Lets reps see whether
    an account has been flagged before (avoiding duplicate flags) and
    what reasons came up.
    """

    model_config = ConfigDict(frozen=True)

    items: list[AccountFlagHistoryItem]


# =====================================================================
# Pins
# =====================================================================
class PinResponse(BaseModel):
    """Result of pin / unpin toggle."""

    model_config = ConfigDict(frozen=True)

    account_id: int
    is_pinned: bool


# =====================================================================
# Account detail (joined view)
# =====================================================================
class FieldAccountDetail(BaseModel):
    """Result of ``GET /api/field/accounts/{id}``.

    Account header + recent visit-notes timeline (last 50) + computed
    priority signals.  One request = full account page.
    """

    model_config = ConfigDict(frozen=True)

    summary: FieldAccountSummary
    notes: list[VisitNote]


# =====================================================================
# Admin oversight
# =====================================================================
class AdminRepRow(BaseModel):
    """One row in the admin rep roster."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    territory_states: list[str]
    is_active: bool

    visit_count_30d: int
    last_visit_at: datetime | None


class AdminRepsResponse(BaseModel):
    """Result of ``GET /api/admin/field/reps``."""

    model_config = ConfigDict(frozen=True)

    items: list[AdminRepRow]


class AdminActivityRow(BaseModel):
    """One row in the cross-rep activity feed."""

    model_config = ConfigDict(frozen=True)

    note_id: int
    rep_id: uuid.UUID
    rep_name: str
    account_id: int
    account_name: str
    account_state: str | None

    visit_date: date
    channel: VisitChannel
    outcome: VisitOutcome
    note_excerpt: str

    created_at: datetime


class AdminActivityResponse(BaseModel):
    """Result of ``GET /api/admin/field/activity``."""

    model_config = ConfigDict(frozen=True)

    items: list[AdminActivityRow]
    total: int
    limit: int
    offset: int
