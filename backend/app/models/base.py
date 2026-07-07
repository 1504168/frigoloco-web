"""Declarative base shared by every ORM model.

All model modules register their tables on ``Base.metadata``. Note that the 34
tables defined in ``architecture/database/schema.sql`` are created by that SQL
file (run via ``scripts/apply_schema.py``) — the ORM classes only mirror them so
the application can query with typed ``Mapped[]`` attributes. Only the two sync
tables in ``sync.py`` (absent from schema.sql) are created from this metadata via
``create_all(checkfirst=True)``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy 2.0 declarative base."""
