"""Supplier CRUD plus yearly agreements and the weekly delivery schedule."""

from __future__ import annotations

import datetime

from fastapi import Depends, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import (
    Product,
    Supplier,
    SupplierAgreement,
    SupplierDeliverySchedule,
)
from app.schemas.masters import (
    Page,
    PaginationParams,
    SupplierAgreementCreate,
    SupplierAgreementRead,
    SupplierCategoryLink,
    SupplierCreate,
    SupplierDeliveryScheduleItem,
    SupplierDeliveryScheduleReplace,
    SupplierNextDeliveryRead,
    SupplierRead,
    SupplierUpdate,
    api_error,
    make_router,
    pagination,
)
from app.services.supplier_schedule_service import LOCAL_TIMEZONE, find_next_supplier_delivery

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


@router.get("/{supplier_id}/agreements", response_model=list[SupplierAgreementRead])
def list_supplier_agreements(
    supplier_id: int, session: Session = Depends(get_db)
) -> list[SupplierAgreementRead]:
    _get_or_404(supplier_id, session)
    agreements = session.execute(
        select(SupplierAgreement)
        .where(SupplierAgreement.supplier_id == supplier_id)
        .order_by(SupplierAgreement.year.desc(), SupplierAgreement.id)
    ).scalars()
    return [SupplierAgreementRead.model_validate(agreement) for agreement in agreements]


@router.post(
    "/{supplier_id}/agreements",
    response_model=SupplierAgreementRead,
    status_code=status.HTTP_201_CREATED,
)
def create_supplier_agreement(
    supplier_id: int,
    body: SupplierAgreementCreate,
    session: Session = Depends(get_db),
) -> SupplierAgreementRead:
    _get_or_404(supplier_id, session)
    agreement = SupplierAgreement(supplier_id=supplier_id, **body.model_dump())
    session.add(agreement)
    session.commit()
    session.refresh(agreement)
    return SupplierAgreementRead.model_validate(agreement)


@router.delete(
    "/{supplier_id}/agreements/{agreement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_supplier_agreement(
    supplier_id: int,
    agreement_id: int,
    session: Session = Depends(get_db),
) -> None:
    agreement = session.get(SupplierAgreement, agreement_id)
    if agreement is None or agreement.supplier_id != supplier_id:
        raise api_error(404, "not_found", "Agreement not found", {"id": agreement_id})
    session.delete(agreement)
    session.commit()


@router.get(
    "/{supplier_id}/delivery-schedule",
    response_model=list[SupplierDeliveryScheduleItem],
)
def get_supplier_delivery_schedule(
    supplier_id: int, session: Session = Depends(get_db)
) -> list[SupplierDeliveryScheduleItem]:
    _get_or_404(supplier_id, session)
    schedules = session.execute(
        select(SupplierDeliverySchedule)
        .where(SupplierDeliverySchedule.supplier_id == supplier_id)
        .order_by(SupplierDeliverySchedule.delivery_weekday)
    ).scalars()
    return [SupplierDeliveryScheduleItem.model_validate(schedule) for schedule in schedules]


@router.put(
    "/{supplier_id}/delivery-schedule",
    response_model=list[SupplierDeliveryScheduleItem],
)
def replace_supplier_delivery_schedule(
    supplier_id: int,
    body: SupplierDeliveryScheduleReplace,
    session: Session = Depends(get_db),
) -> list[SupplierDeliveryScheduleItem]:
    """Replace the whole weekly schedule; one row per delivery weekday."""
    _get_or_404(supplier_id, session)
    delivery_weekdays = [item.delivery_weekday for item in body.items]
    if len(delivery_weekdays) != len(set(delivery_weekdays)):
        raise api_error(422, "validation_error", "Duplicate delivery weekday", None)
    session.execute(
        delete(SupplierDeliverySchedule).where(
            SupplierDeliverySchedule.supplier_id == supplier_id
        )
    )
    for item in body.items:
        session.add(SupplierDeliverySchedule(supplier_id=supplier_id, **item.model_dump()))
    session.commit()
    return get_supplier_delivery_schedule(supplier_id, session)


@router.get("/{supplier_id}/next-delivery", response_model=SupplierNextDeliveryRead | None)
def get_supplier_next_delivery(
    supplier_id: int,
    ordered_at: datetime.datetime | None = Query(
        default=None,
        description="When the order is placed (default now). Naive = Europe/Brussels time.",
    ),
    session: Session = Depends(get_db),
) -> SupplierNextDeliveryRead | None:
    """Next delivery date and its order deadline; null when the supplier has no schedule."""
    _get_or_404(supplier_id, session)
    order_moment = ordered_at or datetime.datetime.now(LOCAL_TIMEZONE)
    next_delivery = find_next_supplier_delivery(session, supplier_id, order_moment)
    if next_delivery is None:
        return None
    return SupplierNextDeliveryRead(
        delivery_date=next_delivery.delivery_date,
        order_deadline=next_delivery.order_deadline,
    )
