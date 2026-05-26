"""SQLAlchemy 2.0 ORM models for the ``sales`` Postgres schema.

These mirror the tables defined in ``db/migrations/001_sales_schema.sql``.
The SQL is the source of truth — these models never CREATE or ALTER
tables (we do not call ``Base.metadata.create_all()``).

Importing every model here ensures SQLAlchemy registers them on the
shared ``Base.metadata``, which is needed for relationship resolution
and for the smoke test that asserts all tables are under the ``sales``
schema.
"""

from hy_sales.models.account import Account
from hy_sales.models.app_config import AppConfig
from hy_sales.models.base import Base
from hy_sales.models.customer import Customer
from hy_sales.models.customer_alias import CustomerAlias
from hy_sales.models.depletion import Depletion
from hy_sales.models.distributor import Distributor
from hy_sales.models.file_upload import FileUpload
from hy_sales.models.invoice import Invoice
from hy_sales.models.invoice_line import InvoiceLine
from hy_sales.models.product import Product
from hy_sales.models.product_alias import ProductAlias

__all__ = [
    "Account",
    "AppConfig",
    "Base",
    "Customer",
    "CustomerAlias",
    "Depletion",
    "Distributor",
    "FileUpload",
    "Invoice",
    "InvoiceLine",
    "Product",
    "ProductAlias",
]
