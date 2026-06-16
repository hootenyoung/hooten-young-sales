"""SQLAlchemy 2.0 ORM models for the Hooten Young backend.

Three physically isolated domains, three Postgres schemas:

* ``sales`` — QuickBooks-feed wholesale sales (invoices to distributors).
    AppConfig, Customer, CustomerAlias, Distributor, FileUpload, Invoice,
    InvoiceLine, Product, ProductAlias.

* ``depletions`` — iDIG-feed retail pull-through.
    DepAccount, DepFact, DepFileUpload, DepProduct, DepProductAlias.

* ``auth`` — authentication + authorization.
    AuthRole, AuthUser, AuthUserRole, AuthPasswordResetToken, AuthAuditLog.

The SQL migrations under ``db/migrations/`` are the source of truth for
table structure. These models never CREATE or ALTER tables (we never
call ``Base.metadata.create_all()``).

Importing every model here registers them on ``Base.metadata`` so the
smoke test that enumerates known tables can see them all.
"""

from hy_sales.models.app_config import AppConfig
from hy_sales.models.auth_audit_log import AuthAuditLog
from hy_sales.models.auth_password_reset_token import AuthPasswordResetToken
from hy_sales.models.auth_role import AuthRole
from hy_sales.models.auth_user import AuthUser
from hy_sales.models.auth_user_role import AuthUserRole
from hy_sales.models.base import Base
from hy_sales.models.customer import Customer
from hy_sales.models.customer_alias import CustomerAlias
from hy_sales.models.dep_account import DepAccount
from hy_sales.models.dep_fact import DepFact
from hy_sales.models.dep_file_upload import DepFileUpload
from hy_sales.models.dep_product import DepProduct
from hy_sales.models.dep_product_alias import DepProductAlias
from hy_sales.models.distributor import Distributor
from hy_sales.models.file_upload import FileUpload
from hy_sales.models.invoice import Invoice
from hy_sales.models.invoice_line import InvoiceLine
from hy_sales.models.product import Product
from hy_sales.models.product_alias import ProductAlias

__all__ = [
    "AppConfig",
    "AuthAuditLog",
    "AuthPasswordResetToken",
    "AuthRole",
    "AuthUser",
    "AuthUserRole",
    "Base",
    "Customer",
    "CustomerAlias",
    "DepAccount",
    "DepFact",
    "DepFileUpload",
    "DepProduct",
    "DepProductAlias",
    "Distributor",
    "FileUpload",
    "Invoice",
    "InvoiceLine",
    "Product",
    "ProductAlias",
]
