"""Smoke tests — proves the package imports, models register, app builds."""

from __future__ import annotations


def test_package_imports() -> None:
    """The hy_sales package imports without error."""
    import hy_sales

    assert hy_sales.__version__


def test_models_register_under_sales_schema() -> None:
    """Every ORM table registers under the 'sales' Postgres schema."""
    from hy_sales.models import Base

    assert Base.metadata.tables, "no models registered"
    for table in Base.metadata.tables.values():
        assert table.schema == "sales", (
            f"Table {table.name!r} is not in 'sales' schema (got {table.schema!r})"
        )


def test_models_match_expected_tables() -> None:
    """The 10 sales tables we expect are registered."""
    from hy_sales.models import Base

    table_names = {t.name for t in Base.metadata.tables.values()}
    expected = {
        "app_config",
        "file_uploads",
        "products",
        "product_aliases",
        "distributors",
        "customers",
        "customer_aliases",
        "accounts",
        "invoices",
        "invoice_lines",
        "depletions",
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
    assert "/api/sales/white-space" in paths
    assert "/api/sales/order-analysis" in paths
    assert "/api/sales/risk" in paths
