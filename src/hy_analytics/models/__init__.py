"""SQLAlchemy ORM models.

All models inherit from ``Base`` defined here. Add new models as siblings in
this package (one file per logical entity group, e.g. ``social.py``,
``competitor.py``, ``insight.py``).

Migrations are managed by Alembic (to be initialized when the first model
lands). Run migrations via ``uv run alembic upgrade head``.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models in hy_analytics."""
