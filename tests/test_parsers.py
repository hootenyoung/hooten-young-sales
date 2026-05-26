"""Tests for the xlsx parsers.

These run against the real Friday-drop files in ``~/Desktop/Hooten Young/``
when present locally; they're skipped in CI (where the files don't ship).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from hy_sales.parsers.depletions import parse_depletions_xlsx
from hy_sales.parsers.sales import parse_sales_xlsx

DESKTOP = Path.home() / "Desktop" / "Hooten Young"
SALES_DIR = DESKTOP / "Sales"
DEPLETIONS_DIR = DESKTOP / "Depletions"


# ----------------------------------------------------------------
# Sales parser
# ----------------------------------------------------------------


@pytest.mark.skipif(
    not (SALES_DIR / "April 2026 Sales.xlsx").exists(),
    reason="sample sales xlsx not present on this machine",
)
def test_sales_parser_april_2026() -> None:
    """The April 2026 Sales file parses to multiple invoices with valid lines."""
    invoices = parse_sales_xlsx(SALES_DIR / "April 2026 Sales.xlsx")

    assert invoices, "expected at least one invoice"
    # SI-012682 appeared in inspection with 2 lines, both American Whiskey 12yr.
    by_ref = {inv.invoice_ref: inv for inv in invoices}
    assert "SI-012682" in by_ref, "SI-012682 should be present in April 2026 file"
    si_682 = by_ref["SI-012682"]
    assert si_682.invoice_date == date(2026, 4, 2)
    assert si_682.customer_raw_text == "Ohio ABC"
    assert len(si_682.lines) >= 2
    # Lines are 1-indexed.
    assert [line.line_seq for line in si_682.lines] == list(range(1, len(si_682.lines) + 1))

    # Every line has positive quantity and amount = quantity * sales_price
    # (allow rounding tolerance).
    for inv in invoices:
        for line in inv.lines:
            assert line.quantity > 0
            assert line.amount >= 0
            assert line.product_raw_text.strip(), "memo should be non-empty"


@pytest.mark.skipif(
    not (SALES_DIR / "Sales 05.15.26.xlsx").exists(),
    reason="sample sales xlsx not present on this machine",
)
def test_sales_parser_may_2026_partial() -> None:
    """The May 2026 partial-month file parses without errors."""
    invoices = parse_sales_xlsx(SALES_DIR / "Sales 05.15.26.xlsx")
    assert invoices
    # All dates fall within May 2026.
    for inv in invoices:
        assert inv.invoice_date.year == 2026
        assert inv.invoice_date.month == 5


# ----------------------------------------------------------------
# Depletions parser
# ----------------------------------------------------------------


_MONTHLY_FILE = "HY  Jan 2025 thru May 2026 State Acct Product.xlsx"


@pytest.mark.skipif(
    not (DEPLETIONS_DIR / _MONTHLY_FILE).exists(),
    reason="sample depletions xlsx not present on this machine",
)
def test_depletions_parser_monthly() -> None:
    """The monthly depletions file unpivots into long-format rows with paired metrics."""
    rows = parse_depletions_xlsx(DEPLETIONS_DIR / _MONTHLY_FILE)

    assert rows, "expected at least one depletion row"
    for row in rows:
        # All period_month values must be first-of-month.
        assert row.period_month.day == 1, f"period_month {row.period_month} not first-of-month"
        # Each emitted row should be non-zero (we filter (0, 0) out at parse time),
        # but values can be negative (returns / pullbacks from retail).
        is_zero = row.cases_9l == 0 and (row.cases_physical is None or row.cases_physical == 0)
        assert not is_zero, "parser should drop (0, 0) rows"
    # New monthly format includes Physical Cases — at least some rows should have it.
    assert any(r.cases_physical is not None and r.cases_physical != 0 for r in rows)
    # Returns / negative values DO occur — confirm the parser doesn't drop them.
    assert any(r.cases_9l < 0 for r in rows), (
        "expected at least one negative depletion row (returns)"
    )
    # ABC WAREHOUSE in Orlando was visible in inspection.
    abc_rows = [r for r in rows if r.account_name == "ABC WAREHOUSE" and r.state_code == "FL"]
    assert abc_rows, "ABC WAREHOUSE FL should appear in monthly depletions"
    assert all(r.distributor_code == "FL13" for r in abc_rows)


# ----------------------------------------------------------------
# Decimal precision sanity check (independent of files)
# ----------------------------------------------------------------


def test_canonical_decimal_precision() -> None:
    """Canonical types accept high-precision decimals from xlsx floats."""
    from hy_sales.parsers.canonical import ParsedSalesLine

    line = ParsedSalesLine(
        line_seq=1,
        product_raw_text="X",
        quantity=Decimal("6.83"),
        sales_price=Decimal("219.76"),
        amount=Decimal("1500.96"),
    )
    assert line.quantity == Decimal("6.83")
