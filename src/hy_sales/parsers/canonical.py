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

from pydantic import BaseModel, ConfigDict


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
    product_raw_text: str
    period_month: date
    cases_9l: Decimal
    cases_physical: Decimal | None = None
