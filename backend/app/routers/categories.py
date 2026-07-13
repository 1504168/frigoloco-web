"""Categories - read-only list (seeded fixed set, R8 print order)."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Category
from app.schemas.masters import CategoryRead, make_router

router = make_router(prefix="/api/v1/categories", tags=["categories"])


@router.get("", response_model=list[CategoryRead])
def list_categories(session: Session = Depends(get_db)) -> list[CategoryRead]:
    rows = list(
        session.execute(select(Category).order_by(Category.display_order)).scalars().all()
    )
    return [CategoryRead.model_validate(row) for row in rows]
