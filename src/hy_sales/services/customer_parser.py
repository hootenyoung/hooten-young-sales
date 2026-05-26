"""Heuristic parser for QuickBooks Customer canonical names.

Source data has patterns like:
    "RNDC - TX Houson"              -> ("RNDC", "TX", "distributor")
    "RNDC - MD"                     -> ("RNDC", "MD", "distributor")
    "GREENLIGHT - FL"               -> ("GREENLIGHT", "FL", "distributor")
    "Ohio ABC"                      -> ("Ohio ABC", "OH", "control_state")
    "VA ABC"                        -> ("VA ABC", "VA", "control_state")
    "State of Alabama Alcoholic..." -> ("State of Alabama", "AL", "control_state")
    "OLCC"                          -> ("OLCC", "OR", "control_state")
    "Idaho State Liquor"            -> ("Idaho State Liquor", "ID", "control_state")
    "MLCC"                          -> ("MLCC", "MI", "control_state")
    "NEXCOM - Chino 995"            -> ("NEXCOM", None, "military")
    "Coast Guard - Centreville 459" -> ("Coast Guard", None, "military")
    "MBG"                           -> ("MBG", None, "distributor")
    "Empire Distributors - Nashville" -> ("Empire Distributors", None, "distributor")
        (Nashville is in TN but we don't have a city-to-state lookup;
         left for HY to clean up at the source — see CLAUDE.md)

The parser is best-effort. Names that don't match any pattern fall
through to ``(name, None, "distributor")``. State or distributor stays
NULL when unknown — never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedCustomer:
    """Result of parsing a customer canonical name."""

    distributor_name: str | None
    state_code: str | None
    channel: str  # 'distributor' | 'control_state' | 'military' | 'other'


# US states + DC.
STATE_CODES: frozenset[str] = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

# State full names → 2-letter codes (lowercase keys for case-insensitive lookup).
STATE_NAME_TO_CODE: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


# Known control-state buyers — (regex, canonical name, state code).
# Order matters: more specific patterns first.
_CONTROL_STATE_FIXED: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bohio abc\b", re.IGNORECASE), "Ohio ABC", "OH"),
    (re.compile(r"\bva abc\b", re.IGNORECASE), "VA ABC", "VA"),
    (re.compile(r"\bmd abc\b", re.IGNORECASE), "MD ABC", "MD"),
    (re.compile(r"\bnc abc\b", re.IGNORECASE), "NC ABC", "NC"),
    (re.compile(r"\bms abc\b", re.IGNORECASE), "MS ABC", "MS"),
    (re.compile(r"\bmt abc\b", re.IGNORECASE), "MT ABC", "MT"),
    (re.compile(r"\bsc abc\b", re.IGNORECASE), "SC ABC", "SC"),
    (re.compile(r"\bme abc\b", re.IGNORECASE), "ME ABC", "ME"),
    (re.compile(r"\bnh abc\b", re.IGNORECASE), "NH ABC", "NH"),
    (re.compile(r"\bwv abc\b", re.IGNORECASE), "WV ABC", "WV"),
    (re.compile(r"\bvt abc\b", re.IGNORECASE), "VT ABC", "VT"),
    (re.compile(r"\bwy abc\b", re.IGNORECASE), "WY ABC", "WY"),
    (re.compile(r"\bia abc\b", re.IGNORECASE), "IA ABC", "IA"),
    (re.compile(r"\bal abc\b", re.IGNORECASE), "AL ABC", "AL"),
    (re.compile(r"\bolcc\b", re.IGNORECASE), "OLCC", "OR"),
    (re.compile(r"\bmlcc\b", re.IGNORECASE), "MLCC", "MI"),
    (re.compile(r"\bidaho state liquor\b", re.IGNORECASE), "Idaho State Liquor", "ID"),
    (re.compile(r"\butah doabc\b|\butah dabc\b", re.IGNORECASE), "Utah DABC", "UT"),
    (re.compile(r"\bpennsylvania (state )?liquor\b|\bplcb\b", re.IGNORECASE), "PLCB", "PA"),
]

# "State of <name>..." pattern — extract the state name.
_STATE_OF_PATTERN = re.compile(
    r"^state of ([a-z ]+?)(?:\s+alcoholic|\s+liquor|\s+abc|$)",
    re.IGNORECASE,
)

# Military channels.
_MILITARY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bnexcom\b", re.IGNORECASE), "NEXCOM"),
    (re.compile(r"\bcoast guard\b", re.IGNORECASE), "Coast Guard"),
    (re.compile(r"\baafes\b", re.IGNORECASE), "AAFES"),
    (re.compile(r"\bmwr\b", re.IGNORECASE), "MWR"),
    (re.compile(r"\bcommissary\b", re.IGNORECASE), "Commissary"),
]


def parse_customer_name(name: str) -> ParsedCustomer:
    """Parse a customer canonical name into (distributor_name, state_code, channel).

    Returns a frozen ``ParsedCustomer``. Unmatched names default to
    ``(name, None, "distributor")`` so the bare distributor name still
    flows through.
    """
    name = name.strip()
    if not name:
        return ParsedCustomer(None, None, "other")

    # 1. Control-state fixed patterns
    for pattern, canonical, state in _CONTROL_STATE_FIXED:
        if pattern.search(name):
            return ParsedCustomer(canonical, state, "control_state")

    # 2. "State of <name> ..." pattern
    match = _STATE_OF_PATTERN.search(name)
    if match:
        state_name = match.group(1).strip().lower()
        code = STATE_NAME_TO_CODE.get(state_name)
        if code:
            return ParsedCustomer(
                f"State of {state_name.title()}",
                code,
                "control_state",
            )

    # 3. Military
    for pattern, canonical in _MILITARY_PATTERNS:
        if pattern.search(name):
            return ParsedCustomer(canonical, _try_extract_state(name), "military")

    # 4. "Distributor - STATE City" or "Distributor - STATE"
    if " - " in name:
        head, _, tail = name.partition(" - ")
        distributor = head.strip()
        tokens = tail.strip().split()
        if tokens:
            first = tokens[0].upper().rstrip(",.")
            if first in STATE_CODES:
                return ParsedCustomer(distributor, first, "distributor")
        return ParsedCustomer(distributor, None, "distributor")

    # 5. Bare name — distributor with no state info
    return ParsedCustomer(name, None, "distributor")


def _try_extract_state(name: str) -> str | None:
    """Find a stand-alone 2-letter state code anywhere in the name."""
    for match in re.finditer(r"\b[A-Z]{2}\b", name):
        token = match.group(0)
        if token in STATE_CODES:
            return token
    return None
