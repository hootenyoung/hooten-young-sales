"""Canonical parsed-row types.

These are the broker-agnostic shapes the parsers produce, that the
services layer writes to the DB. The point of having a stable canonical
type is that broker-specific format changes only affect the parsers —
the canonical types and the services layer stay the same.

Pydantic v2 BaseModel is used so missing/invalid values are caught at
parse time with descriptive errors.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class ParsedSalesLine(BaseModel):
    """One product line on a parsed sales invoice."""

    model_config = ConfigDict(frozen=True)

    line_seq: int
    product_raw_text: str
    quantity: Decimal
    sales_price: Decimal
    amount: Decimal


class ParsedSalesInvoice(BaseModel):
    """One parsed invoice header + its lines."""

    model_config = ConfigDict(frozen=False)  # lines list is appended during parsing

    invoice_ref: str
    invoice_date: date
    transaction_type: str = "invoice"
    customer_raw_text: str
    po_number: str | None = None
    lines: list[ParsedSalesLine]


class ParsedDepletionRow(BaseModel):
    """One (account, product, month) depletion fact.

    ``state_code`` is the account's physical state. ``dist_state_code``
    is the servicing distributor's state — usually the same, but can
    differ (a distributor in one state servicing accounts in another).
    """

    model_config = ConfigDict(frozen=True)

    state_code: str | None
    dist_state_code: str | None = None
    account_name: str
    account_address: str | None
    account_city: str | None
    account_county: str | None = None
    account_zip: str | None = None
    distributor_code: str | None
    # Broker's premises classification:
    #   'ON'  — on-premises (bars, restaurants)
    #   'OFF' — off-premises (liquor stores, retail)
    #   'NA'  — broker actively classified as not-applicable (clubs,
    #           military exchanges, cigar lounges, etc.). Distinct from
    #           NULL, which means "we don't have this info" — preserve
    #           NA as its own state so the distinction is queryable.
    #   None  — source layout doesn't carry the column, or the cell
    #           was empty / whitespace / an unrecognized string.
    premises_type: str | None = None
    product_raw_text: str
    period_month: date
    cases_9l: Decimal
    cases_physical: Decimal | None = None

    @field_validator("premises_type", mode="before")
    @classmethod
    def _validate_premises_type(cls, v: str | None) -> str | None:
        """Coerce premises to 'ON' / 'OFF' / 'NA' / None.

        Anything outside the three real values — empty string, weird
        broker codes — collapses to None.
        """
        if v is None:
            return None
        s = str(v).strip().upper()
        return s if s in {"ON", "OFF", "NA"} else None
