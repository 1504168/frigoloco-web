"""Supplier CRUD."""

from __future__ import annotations

from fastapi import Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Product, Supplier
from app.schemas.masters import (
    Page,
    PaginationParams,
    SupplierCategoryLink,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
    api_error,
    make_router,
    pagination,
)

router = make_router(prefix="/api/v1/suppliers", tags=["suppliers"])


def _get_or_404(supplier_id: int, session: Session) -> Supplier:
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise api_error(404, "not_found", "Supplier not found", {"id": supplier_id})
    return supplier


@router.get("", response_model=Page[SupplierRead])
def list_suppliers(
    page: PaginationParams = Depends(pagination),
    category_id: int | None = Query(
        default=None,
        description="Only suppliers with at least one product in this category.",
    ),
    session: Session = Depends(get_db),
) -> Page[SupplierRead]:
    filters = []
    if category_id is not None:
        supplies_category = (
            select(Product.id)
            .where(Product.supplier_id == Supplier.id)
            .where(Product.category_id == category_id)
            .exists()
        )
        filters.append(supplies_category)

    count_stmt = select(func.count()).select_from(Supplier).where(*filters)
    total = session.execute(count_stmt).scalar_one()
    suppliers_by_name = (
        select(Supplier)
        .where(*filters)
        .order_by(func.lower(Supplier.name), Supplier.id)
        .limit(page.limit)
        .offset(page.offset)
    )
    rows = session.execute(suppliers_by_name).scalars().all()
    return Page(
        items=[SupplierRead.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/category-links", response_model=list[SupplierCategoryLink])
def list_supplier_category_links(
    session: Session = Depends(get_db),
) -> list[SupplierCategoryLink]:
    """Every (supplier, category) pair with at least one product, for client-side filters."""
    distinct_pairs = (
        select(Product.supplier_id, Product.category_id)
        .where(Product.supplier_id.is_not(None))
        .distinct()
    )
    rows = session.execute(distinct_pairs).all()
    return [
        SupplierCategoryLink(supplier_id=row.supplier_id, category_id=row.category_id)
        for row in rows
    ]


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier(
    body: SupplierCreate, session: Session = Depends(get_db)
) -> SupplierRead:
    supplier = Supplier(**body.model_dump())
    session.add(supplier)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(409, "conflict", "Supplier name already exists", {"name": body.name}) from exc
    session.refresh(supplier)
    return SupplierRead.model_validate(supplier)


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier(supplier_id: int, session: Session = Depends(get_db)) -> SupplierRead:
    return SupplierRead.model_validate(_get_or_404(supplier_id, session))


@router.put("/{supplier_id}", response_model=SupplierRead)
def update_supplier(
    supplier_id: int, body: SupplierUpdate, session: Session = Depends(get_db)
) -> SupplierRead:
    supplier = _get_or_404(supplier_id, session)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(409, "conflict", "Supplier name already exists") from exc
    session.refresh(supplier)
    return SupplierRead.model_validate(supplier)


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(supplier_id: int, session: Session = Depends(get_db)) -> None:
    supplier = _get_or_404(supplier_id, session)
    session.delete(supplier)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "Supplier is referenced and cannot be deleted", {"id": supplier_id}
        ) from exc
