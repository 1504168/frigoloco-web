"""Which categories still hold an active product (the others are historic)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.husky.sync import EFFECTIVE_STATUS_ACTIVE, effective_status_clause
from app.models.master import Product


def load_category_ids_with_active_products(session: Session) -> set[int]:
    """Ids of categories with at least one effectively active product, in one query."""
    active_clause = effective_status_clause(Product, EFFECTIVE_STATUS_ACTIVE)
    category_ids = session.execute(
        select(Product.category_id).where(active_clause).distinct()
    ).scalars()
    return set(category_ids)
