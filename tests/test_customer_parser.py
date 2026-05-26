"""Unit tests for the customer-name parser."""

from __future__ import annotations

import pytest

from hy_sales.services.customer_parser import ParsedCustomer, parse_customer_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Distributor + state + territory
        ("RNDC - TX Houson", ParsedCustomer("RNDC", "TX", "distributor")),
        ("RNDC - TX Schertz", ParsedCustomer("RNDC", "TX", "distributor")),
        ("RNDC - TX Grand Prairie", ParsedCustomer("RNDC", "TX", "distributor")),
        ("RNDC - MD", ParsedCustomer("RNDC", "MD", "distributor")),
        ("RNDC - CO", ParsedCustomer("RNDC", "CO", "distributor")),
        ("GREENLIGHT - FL", ParsedCustomer("GREENLIGHT", "FL", "distributor")),
        # Distributor + city (no state code)
        (
            "Empire Distributors - Nashville",
            ParsedCustomer("Empire Distributors", None, "distributor"),
        ),
        # Control-state buyers
        ("Ohio ABC", ParsedCustomer("Ohio ABC", "OH", "control_state")),
        ("VA ABC", ParsedCustomer("VA ABC", "VA", "control_state")),
        (
            "State of Alabama Alcoholic Beverage Control Board",
            ParsedCustomer("State of Alabama", "AL", "control_state"),
        ),
        ("OLCC", ParsedCustomer("OLCC", "OR", "control_state")),
        ("MLCC", ParsedCustomer("MLCC", "MI", "control_state")),
        ("Idaho State Liquor", ParsedCustomer("Idaho State Liquor", "ID", "control_state")),
        # Military
        ("NEXCOM - Chino 995", ParsedCustomer("NEXCOM", None, "military")),
        (
            "Coast Guard - Centreville 459",
            ParsedCustomer("Coast Guard", None, "military"),
        ),
        # Bare distributor
        ("MBG", ParsedCustomer("MBG", None, "distributor")),
    ],
)
def test_parse_customer_name(name: str, expected: ParsedCustomer) -> None:
    assert parse_customer_name(name) == expected


def test_empty_name_returns_other() -> None:
    assert parse_customer_name("") == ParsedCustomer(None, None, "other")
    assert parse_customer_name("   ") == ParsedCustomer(None, None, "other")


def test_unknown_pattern_falls_through_to_distributor() -> None:
    parsed = parse_customer_name("Some Random Buyer Inc")
    assert parsed.distributor_name == "Some Random Buyer Inc"
    assert parsed.state_code is None
    assert parsed.channel == "distributor"


def test_dash_pattern_unknown_state_code_keeps_distributor() -> None:
    # 'ZZ' is not a real state code — should not be extracted.
    parsed = parse_customer_name("FOO - ZZ Bar")
    assert parsed.distributor_name == "FOO"
    assert parsed.state_code is None
