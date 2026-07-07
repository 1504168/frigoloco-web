"""Supplier CRUD."""

from __future__ import annotations

from fastapi import Depends, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Supplier
from app.schemas.masters import (
    Page,
    PaginationParams,
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
    session: Session = Depends(get_db),
) -> Page[SupplierRead]:
    total = session.execute(select(func.count()).select_from(Supplier)).scalar_one()
    rows = list(
        session.execute(
            select(Supplier).order_by(Supplier.name).limit(page.limit).offset(page.offset)
        )
        .scalars()
        .all()
    )
    return Page(
        items=[SupplierRead.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )


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
