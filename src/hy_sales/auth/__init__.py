"""FastAPI auth dependencies and route gating helpers.

This package wires the cryptographic primitives in ``hy_sales.security``
into FastAPI's dependency system. Routes use these dependencies to:

* Identify the caller (``get_current_user``).
* Gate access to a specific role (``require_role('depletions')``).
* Gate access to any of multiple roles (``require_any_role('admin', 'sales')``).
"""

from hy_sales.auth.dependencies import (
    CurrentUser,
    get_current_user,
    require_any_role,
    require_role,
)

__all__ = [
    "CurrentUser",
    "get_current_user",
    "require_any_role",
    "require_role",
]
