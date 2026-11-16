"""Categories - read-only list (seeded fixed set, R8 print order)."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Category
from app.schemas.masters import CategoryRead, make_router
from app.services.category_activity_service import load_category_ids_with_active_products

router = make_router(prefix="/api/v1/categories", tags=["categories"])


@router.get("", response_model=list[CategoryRead])
def list_categories(session: Session = Depends(get_db)) -> list[CategoryRead]:
    ordered_categories = select(Category).order_by(Category.display_order, Category.name)
    rows = list(session.execute(ordered_categories).scalars().all())
    active_category_ids = load_category_ids_with_active_products(session)
    return [
        CategoryRead.model_validate(row).model_copy(
            update={"has_active_products": row.id in active_category_ids}
        )
        for row in rows
    ]
