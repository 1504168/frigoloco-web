"""Product tags (contains_pork, vegan, ...) matched by client exclude_tag rules."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Product, ProductTag
from app.schemas.masters import ProductTagsReplace, api_error, make_router

router = make_router(prefix="/api/v1", tags=["product-tags"])

SUGGESTED_PRODUCT_TAGS = (
    "contains_pork",
    "contains_alcohol",
    "vegetarian",
    "vegan",
    "contains_nuts",
    "contains_gluten",
    "halal",
)


@router.get("/product-tags", response_model=list[str])
def list_product_tags(session: Session = Depends(get_db)) -> list[str]:
    """The suggested tags plus every tag already used on a product, sorted."""
    used_tags = session.execute(select(ProductTag.tag).distinct()).scalars()
    known_tags = set(SUGGESTED_PRODUCT_TAGS) | set(used_tags)
    return sorted(known_tags)


@router.get("/products/{product_id}/tags", response_model=list[str])
def get_product_tags(product_id: int, session: Session = Depends(get_db)) -> list[str]:
    _ensure_product_exists(session, product_id)
    tags = session.execute(
        select(ProductTag.tag)
        .where(ProductTag.product_id == product_id)
        .order_by(ProductTag.tag)
    ).scalars()
    return list(tags)


@router.put("/products/{product_id}/tags", response_model=list[str])
def replace_product_tags(
    product_id: int,
    body: ProductTagsReplace,
    session: Session = Depends(get_db),
) -> list[str]:
    _ensure_product_exists(session, product_id)
    session.execute(delete(ProductTag).where(ProductTag.product_id == product_id))
    for tag in body.tags:
        session.add(ProductTag(product_id=product_id, tag=tag))
    session.commit()
    return body.tags


def _ensure_product_exists(session: Session, product_id: int) -> None:
    if session.get(Product, product_id) is None:
        raise api_error(404, "not_found", "Product not found", {"id": product_id})
