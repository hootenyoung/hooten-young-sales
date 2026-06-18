"""Priority + cooldown logic for the field-rep CRM.

A single source of truth for two questions every page asks:

  1. **Is this account eligible to show up in Today's list right now?**
     → ``is_eligible(last_visit_outcome, last_visit_date, today)``

  2. **What's its priority score?**
     → ``compute_priority(days_since_visit, depletions_flagged,
        is_pinned)``

The rules are designed to be obvious-on-read:

* Time since last visit is the bedrock — longer-since-visit means
  higher score, linearly.
* Pin trumps everything (+100 score boost).
* Depletions-flag is additive (+30 score boost).
* Outcome-driven cooldowns suppress an account for N days after a visit
  — see :data:`OUTCOME_COOLDOWN_DAYS`.  An "ordered" visit means we
  give the buyer 30 days breathing room; a "no_response" means try
  again in 3 days.
* Never-visited accounts default to a "days since" of 365 — they don't
  rocket past every long-aged account, but they get strong priority.

If any of these numbers need to be tuned, edit them here.  Every
endpoint pulls from this module.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

# =====================================================================
# Tunable constants
# =====================================================================

#: Score boost for a manually-pinned account.  Effectively guarantees
#: inclusion in Today's list short of the account being in cooldown.
PIN_BOOST: Final[int] = 100

#: Score boost for accounts the depletions follow-up tracker has
#: surfaced (declining or quiet retail performance).  Additive on top
#: of the time-since-visit base.
DEPLETIONS_FLAG_BOOST: Final[int] = 30

#: Cap on the "days since last visit" component of the score.  Never-
#: visited accounts get this value — high enough to dominate, capped
#: so a 5-year-old visit doesn't dwarf a 60-day pinned account.
NEVER_VISITED_DAYS: Final[int] = 365

#: How many days an account is suppressed after a visit, by outcome.
#: Drives :func:`is_eligible` and :func:`next_eligible_date`.
OUTCOME_COOLDOWN_DAYS: Final[dict[str, int]] = {
    "ordered": 30,
    "follow_up_needed": 7,
    "no_response": 3,
    "declined": 60,
    "info_only": 14,
}

#: Default cap on Today's list size when the caller doesn't specify.
DEFAULT_TODAY_LIMIT: Final[int] = 10


# =====================================================================
# Public functions
# =====================================================================
def compute_priority(
    *,
    days_since_last_visit: int | None,
    depletions_flagged: bool,
    is_pinned: bool,
) -> int:
    """Return the priority score for an account.

    Higher = surface sooner.  ``None`` for never-visited → uses
    :data:`NEVER_VISITED_DAYS`.

    Pin and depletions flags are additive boosts on top of the time
    component, so a pinned 50-day-stale flagged account scores
    50 + 100 + 30 = 180.
    """
    base = NEVER_VISITED_DAYS if days_since_last_visit is None else days_since_last_visit
    score = base
    if depletions_flagged:
        score += DEPLETIONS_FLAG_BOOST
    if is_pinned:
        score += PIN_BOOST
    return score


def cooldown_days_for(outcome: str) -> int:
    """How many days to suppress an account after a visit with this
    outcome.  Returns 0 for unknown outcomes (defensive default —
    callers should use the typed Literal but defending against bad
    DB rows here keeps the rest of the pipeline simple).
    """
    return OUTCOME_COOLDOWN_DAYS.get(outcome, 0)


def next_eligible_date(*, last_visit_date: date, last_outcome: str) -> date:
    """The earliest date this account can resurface in Today's list."""
    return last_visit_date + timedelta(days=cooldown_days_for(last_outcome))


def is_eligible(
    *,
    last_visit_date: date | None,
    last_outcome: str | None,
    today: date,
) -> bool:
    """True if the account can appear in Today's list right now.

    Never-visited (``last_visit_date is None``) → always eligible.
    Otherwise: eligible once ``next_eligible_date`` has passed.

    Pinning does NOT override cooldown — a rep who just visited an
    account yesterday and pinned it should still not see it tomorrow.
    The pin's job is to lift it to the top of Today *when it does come
    back into eligibility*.
    """
    if last_visit_date is None or last_outcome is None:
        return True
    return today >= next_eligible_date(
        last_visit_date=last_visit_date,
        last_outcome=last_outcome,
    )
