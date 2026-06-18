"""Unit tests for the field-rep priority + cooldown service."""

from __future__ import annotations

from datetime import date, timedelta

from hy_sales.services.field_priority import (
    DEPLETIONS_FLAG_BOOST,
    NEVER_VISITED_DAYS,
    PIN_BOOST,
    compute_priority,
    cooldown_days_for,
    is_eligible,
    next_eligible_date,
)


def test_priority_never_visited_uses_cap() -> None:
    """Never-visited accounts score at the configured cap."""
    score = compute_priority(
        days_since_last_visit=None,
        depletions_flagged=False,
        is_pinned=False,
    )
    assert score == NEVER_VISITED_DAYS


def test_priority_grows_with_days() -> None:
    """More time since last visit → higher score."""
    s10 = compute_priority(days_since_last_visit=10, depletions_flagged=False, is_pinned=False)
    s90 = compute_priority(days_since_last_visit=90, depletions_flagged=False, is_pinned=False)
    assert s90 > s10
    assert s90 - s10 == 80  # purely time-driven, no boosts


def test_priority_pin_adds_pin_boost() -> None:
    base = compute_priority(days_since_last_visit=20, depletions_flagged=False, is_pinned=False)
    pinned = compute_priority(days_since_last_visit=20, depletions_flagged=False, is_pinned=True)
    assert pinned - base == PIN_BOOST


def test_priority_depletions_flag_adds_flag_boost() -> None:
    base = compute_priority(days_since_last_visit=20, depletions_flagged=False, is_pinned=False)
    flagged = compute_priority(days_since_last_visit=20, depletions_flagged=True, is_pinned=False)
    assert flagged - base == DEPLETIONS_FLAG_BOOST


def test_priority_pin_and_flag_are_additive() -> None:
    base = compute_priority(days_since_last_visit=20, depletions_flagged=False, is_pinned=False)
    both = compute_priority(days_since_last_visit=20, depletions_flagged=True, is_pinned=True)
    assert both - base == PIN_BOOST + DEPLETIONS_FLAG_BOOST


def test_cooldown_days_known_outcomes() -> None:
    assert cooldown_days_for("ordered") == 30
    assert cooldown_days_for("follow_up_needed") == 7
    assert cooldown_days_for("no_response") == 3
    assert cooldown_days_for("declined") == 60
    assert cooldown_days_for("info_only") == 14


def test_cooldown_days_unknown_defaults_to_zero() -> None:
    """Defensive: a stray DB value won't blow up the pipeline."""
    assert cooldown_days_for("not_a_real_outcome") == 0


def test_next_eligible_date_adds_cooldown() -> None:
    visit = date(2026, 1, 1)
    assert next_eligible_date(last_visit_date=visit, last_outcome="ordered") == date(2026, 1, 31)
    assert next_eligible_date(last_visit_date=visit, last_outcome="no_response") == date(2026, 1, 4)


def test_eligibility_never_visited_is_eligible() -> None:
    """Never-visited accounts are always eligible regardless of today."""
    assert is_eligible(
        last_visit_date=None,
        last_outcome=None,
        today=date(2026, 6, 1),
    )


def test_eligibility_inside_cooldown_window_is_suppressed() -> None:
    """An ordered-yesterday account is NOT eligible today."""
    yesterday = date(2026, 6, 14)
    today = yesterday + timedelta(days=1)
    assert not is_eligible(
        last_visit_date=yesterday,
        last_outcome="ordered",
        today=today,
    )


def test_eligibility_after_cooldown_resurfaces() -> None:
    """Once cooldown expires, account is eligible again."""
    visit = date(2026, 4, 1)
    today = visit + timedelta(days=30)  # exactly the cooldown — eligible
    assert is_eligible(
        last_visit_date=visit,
        last_outcome="ordered",
        today=today,
    )


def test_eligibility_no_response_short_cooldown() -> None:
    """no_response = 3-day cooldown, so a 4-day-old visit is eligible."""
    visit = date(2026, 4, 1)
    assert is_eligible(
        last_visit_date=visit,
        last_outcome="no_response",
        today=visit + timedelta(days=4),
    )
    assert not is_eligible(
        last_visit_date=visit,
        last_outcome="no_response",
        today=visit + timedelta(days=2),
    )
