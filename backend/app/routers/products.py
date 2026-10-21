"""Product CRUD plus per-fridge price overrides."""

from __future__ import annotations

from fastapi import Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.husky.sync import effective_status_clause
from app.models.master import FridgeProductPrice, Product, Supplier
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.schemas.products import (
    EffectiveStatusFilter,
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
    supplier_id: int | None = Query(default=None),
    search: str | None = Query(
        default=None,
        description="Case-insensitive contains match on product code or name.",
    ),
    status: EffectiveStatusFilter | None = Query(
        default=None,
        description="Filter by effective status (local_status override wins over "
        "Husky is_active); 'all' or omitted means no filter.",
    ),
    session: Session = Depends(get_db),
) -> Page[ProductRead]:
    filters = []
    status_clause = effective_status_clause(Product, status)
    if status_clause is not None:
        filters.append(status_clause)
    if category_id is not None:
        filters.append(Product.category_id == category_id)
    if supplier_id is not None:
        filters.append(Product.supplier_id == supplier_id)
    if search:
        pattern = f"%{search}%"
        filters.append(or_(Product.code.ilike(pattern), Product.name.ilike(pattern)))

    count_stmt = select(func.count()).select_from(Product).where(*filters)
    total = session.execute(count_stmt).scalar_one()
    products_with_supplier = (
        select(Product, Supplier.name)
        .outerjoin(Supplier, Product.supplier_id == Supplier.id)
        .where(*filters)
        .order_by(Product.name)
        .limit(page.limit)
        .offset(page.offset)
    )
    rows = session.execute(products_with_supplier).all()
    items = [_to_read(product, supplier_name) for product, supplier_name in rows]
    return Page(items=items, total=int(total), limit=page.limit, offset=page.offset)


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
    return _read_with_supplier_name(product, session)


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, session: Session = Depends(get_db)) -> ProductRead:
    return _read_with_supplier_name(_get_or_404(product_id, session), session)


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
    return _read_with_supplier_name(product, session)


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


def _read_with_supplier_name(product: Product, session: Session) -> ProductRead:
    supplier_name = None
    if product.supplier_id is not None:
        supplier_name = session.get(Supplier, product.supplier_id).name
    return _to_read(product, supplier_name)


def _to_read(product: Product, supplier_name: str | None) -> ProductRead:
    return ProductRead.model_validate(product).model_copy(
        update={"supplier_name": supplier_name}
    )
