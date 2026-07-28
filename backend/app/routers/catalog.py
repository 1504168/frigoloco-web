"""Catalogue cascade: the Category -> Brand -> Product dependent dropdowns.

Three read-only option endpoints that back the product-selection UX: pick a
category, see only the brands that have products in it, then see only that brand's
products. Each level is just the previous foreign-key filter on ``products``
(``category_id`` -> ``supplier_id``), so the three endpoints share one shape:
minimal ``id``/``name`` options, always returned SORTED, with an optional
``has_active`` filter that restricts to products whose EFFECTIVE status is active
(the manual ``local_status`` override wins over Husky's ``is_active``).

"Brand" is the ``suppliers`` table: Husky's per-product ``productBrand`` string is
normalised into a supplier row (see ``app.husky.sync``), so a brand IS a supplier.
"""

from __future__ import annotations

from fastapi import Depends, Query
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.husky.sync import effective_status_clause
from app.models.master import Category, Product, Supplier
from app.schemas.catalog import BrandOption, CategoryOption, ProductOption
from app.schemas.masters import make_router

router = make_router(prefix="/api/v1/catalog", tags=["catalog"])


@router.get("/categories", response_model=list[CategoryOption])
def list_category_options(
    has_active: bool = Query(
        default=False,
        description="When true, only categories that have at least one ACTIVE "
        "product are returned.",
    ),
    session: Session = Depends(get_db),
) -> list[CategoryOption]:
    """Level 1: categories, sorted by ``display_order`` (the numeric 1..10 prefix)."""
    stmt = select(Category)
    active_clause = _active_products_clause(has_active)
    if active_clause is not None:
        stmt = stmt.where(
            exists().where(Product.category_id == Category.id).where(active_clause)
        )
    stmt = stmt.order_by(Category.display_order)
    return [
        CategoryOption.model_validate(row)
        for row in session.execute(stmt).scalars().all()
    ]


@router.get("/brands", response_model=list[BrandOption])
def list_brand_options(
    category_id: int = Query(description="Category selected at level 1."),
    has_active: bool = Query(
        default=False,
        description="When true, only brands with at least one ACTIVE product in "
        "the category are returned.",
    ),
    session: Session = Depends(get_db),
) -> list[BrandOption]:
    """Level 2: distinct brands (suppliers) with products in ``category_id``, by name."""
    stmt = (
        select(Supplier.id, Supplier.name)
        .join(Product, Product.supplier_id == Supplier.id)
        .where(Product.category_id == category_id)
    )
    active_clause = _active_products_clause(has_active)
    if active_clause is not None:
        stmt = stmt.where(active_clause)
    stmt = stmt.distinct().order_by(Supplier.name)
    return [
        BrandOption(id=row.id, name=row.name)
        for row in session.execute(stmt).all()
    ]


@router.get("/products", response_model=list[ProductOption])
def list_product_options(
    category_id: int = Query(description="Category selected at level 1."),
    brand_id: int | None = Query(
        default=None,
        description="Brand (supplier) selected at level 2. Omit to list every "
        "product in the category.",
    ),
    has_active: bool = Query(
        default=False, description="When true, only ACTIVE products are returned."
    ),
    session: Session = Depends(get_db),
) -> list[ProductOption]:
    """Level 3: products in the category (and brand, if given), sorted by name."""
    stmt = select(Product.id, Product.code, Product.name).where(
        Product.category_id == category_id
    )
    if brand_id is not None:
        stmt = stmt.where(Product.supplier_id == brand_id)
    active_clause = _active_products_clause(has_active)
    if active_clause is not None:
        stmt = stmt.where(active_clause)
    stmt = stmt.order_by(Product.name)
    return [
        ProductOption(id=row.id, code=row.code, name=row.name)
        for row in session.execute(stmt).all()
    ]


def _active_products_clause(has_active: bool):
    """The ``effective status = active`` filter, or None when not requested.

    Reuses the shared ``effective_status_clause`` so the ``local_status`` manual
    override is honoured identically to the rest of the API.
    """
    if not has_active:
        return None
    return effective_status_clause(Product, "active")
