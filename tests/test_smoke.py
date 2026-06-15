"""Smoke tests — proves the package imports, models register, app builds."""

from __future__ import annotations


def test_package_imports() -> None:
    """The hy_sales package imports without error."""
    import hy_sales

    assert hy_sales.__version__


def test_models_register_under_known_schemas() -> None:
    """Every ORM table registers under the 'sales' or 'depletions' schema."""
    from hy_sales.models import Base

    assert Base.metadata.tables, "no models registered"
    for table in Base.metadata.tables.values():
        assert table.schema in {"sales", "depletions"}, (
            f"Table {table.schema}.{table.name!r} is not in an allowed schema"
        )


def test_models_match_expected_tables() -> None:
    """The full set of fully-qualified tables we expect is registered."""
    from hy_sales.models import Base

    table_names = {f"{t.schema}.{t.name}" for t in Base.metadata.tables.values()}
    expected = {
        # Sales schema — QuickBooks-feed wholesale sales
        "sales.app_config",
        "sales.file_uploads",
        "sales.products",
        "sales.product_aliases",
        "sales.distributors",
        "sales.customers",
        "sales.customer_aliases",
        "sales.invoices",
        "sales.invoice_lines",
        # Depletions schema — iDIG-feed retail pull-through
        "depletions.file_uploads",
        "depletions.products",
        "depletions.product_aliases",
        "depletions.accounts",
        "depletions.facts",
    }
    assert table_names == expected, (
        f"Unexpected tables. Missing: {expected - table_names}, Extra: {table_names - expected}"
    )


def test_app_factory_returns_fastapi() -> None:
    """create_app() builds a FastAPI instance with health routes registered."""
    from hy_sales.main import app

    assert app.title == "Hooten Young Sales API"
    paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
    assert "/health" in paths
    assert "/health/ready" in paths
    assert "/api/sales/kpis" in paths
    assert "/api/sales/trend" in paths
    assert "/api/sales/by-product" in paths
    assert "/api/sales/by-state" in paths
    assert "/api/sales/by-distributor" in paths
    assert "/api/depletions/kpis" in paths
    assert "/api/depletions/trend" in paths
    assert "/api/depletions/by-product" in paths
    assert "/api/depletions/by-state" in paths
    assert "/api/depletions/top-accounts" in paths
    assert "/api/depletions/follow-ups" in paths
    assert "/api/depletions/new-vs-lost" in paths
    assert "/api/depletions/velocity" in paths
    assert "/api/depletions/growth-decline" in paths
    assert "/api/depletions/account-monthly-grid" in paths
    assert "/api/sales/white-space" in paths
    assert "/api/sales/order-analysis" in paths
    assert "/api/sales/risk" in paths
