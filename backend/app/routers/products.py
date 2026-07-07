"""Product CRUD plus per-fridge price overrides."""

from __future__ import annotations

from fastapi import Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.husky.sync import effective_status_clause
from app.models.master import FridgeProductPrice, Product
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.schemas.products import (
    FridgePriceItem,
    FridgePriceRead,
    FridgePriceReplace,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)

router = make_router(prefix="/api/v1/products", tags=["products"])


def _get_or_404(product_id: int, session: Session) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise api_error(404, "not_found", "Product not found", {"id": product_id})
    return product


@router.get("", response_model=Page[ProductRead])
def list_products(
    page: PaginationParams = Depends(pagination),
    category_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    status: str | None = Query(
        default=None,
        description="Filter by effective status: active | inactive | cancelled | all "
        "(local_status override wins over Husky is_active).",
    ),
    session: Session = Depends(get_db),
) -> Page[ProductRead]:
    stmt = select(Product)
    count_stmt = select(func.count()).select_from(Product)
    status_clause = effective_status_clause(Product, status)
    if status_clause is not None:
        stmt = stmt.where(status_clause)
        count_stmt = count_stmt.where(status_clause)
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
        count_stmt = count_stmt.where(Product.category_id == category_id)
    if search:
        pattern = f"%{search}%"
        clause = or_(Product.code.ilike(pattern), Product.name.ilike(pattern))
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = session.execute(count_stmt).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(Product.name).limit(page.limit).offset(page.offset)
        )
        .scalars()
        .all()
    )
    return Page(
        items=[ProductRead.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(body: ProductCreate, session: Session = Depends(get_db)) -> ProductRead:
    product = Product(**body.model_dump())
    session.add(product)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "Product code already exists", {"code": body.code}
        ) from exc
    session.refresh(product)
    return ProductRead.model_validate(product)


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, session: Session = Depends(get_db)) -> ProductRead:
    return ProductRead.model_validate(_get_or_404(product_id, session))


@router.put("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int, body: ProductUpdate, session: Session = Depends(get_db)
) -> ProductRead:
    product = _get_or_404(product_id, session)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(409, "conflict", "Product code already exists", None) from exc
    session.refresh(product)
    return ProductRead.model_validate(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, session: Session = Depends(get_db)) -> None:
    product = _get_or_404(product_id, session)
    session.delete(product)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "Product is referenced and cannot be deleted", {"id": product_id}
        ) from exc


@router.get("/{product_id}/fridge-prices", response_model=list[FridgePriceRead])
def get_fridge_prices(
    product_id: int, session: Session = Depends(get_db)
) -> list[FridgePriceRead]:
    _get_or_404(product_id, session)
    rows = list(
        session.execute(
            select(FridgeProductPrice)
            .where(FridgeProductPrice.product_id == product_id)
            .order_by(FridgeProductPrice.fridge_id)
        )
        .scalars()
        .all()
    )
    return [FridgePriceRead.model_validate(row) for row in rows]


@router.put("/{product_id}/fridge-prices", response_model=list[FridgePriceRead])
def replace_fridge_prices(
    product_id: int,
    body: FridgePriceReplace,
    session: Session = Depends(get_db),
) -> list[FridgePriceRead]:
    _get_or_404(product_id, session)
    fridge_ids = [item.fridge_id for item in body.items]
    if len(fridge_ids) != len(set(fridge_ids)):
        raise api_error(422, "validation_error", "Duplicate fridge_id in payload", None)
    for existing in session.execute(
        select(FridgeProductPrice).where(FridgeProductPrice.product_id == product_id)
    ).scalars().all():
        session.delete(existing)
    session.flush()
    for item in body.items:
        session.add(
            FridgeProductPrice(
                fridge_id=item.fridge_id,
                product_id=product_id,
                sales_price=item.sales_price,
            )
        )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "Invalid fridge reference in fridge prices", None
        ) from exc
    return get_fridge_prices(product_id, session)
