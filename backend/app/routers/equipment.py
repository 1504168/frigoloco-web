"""Equipment register CRUD (coffee machines, water filters, vending machines).

Reference data only: monthly fees and rent costs here do not feed the finance P&L.
"""

from __future__ import annotations

from fastapi import Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Equipment, EquipmentCategory, EquipmentOwnership
from app.schemas.masters import (
    EquipmentCreate,
    EquipmentRead,
    Page,
    PaginationParams,
    api_error,
    make_router,
    pagination,
)

router = make_router(prefix="/api/v1/equipment", tags=["equipment"])

SAVE_FAILED_MESSAGE = (
    "Machine code already exists, or the supplier, client or fridge does not exist"
)


@router.get("", response_model=Page[EquipmentRead])
def list_equipment(
    page: PaginationParams = Depends(pagination),
    client_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    equipment_category: EquipmentCategory | None = Query(default=None),
    ownership: EquipmentOwnership | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, description="Matches machine code or type."),
    session: Session = Depends(get_db),
) -> Page[EquipmentRead]:
    filters = []
    if client_id is not None:
        filters.append(Equipment.client_id == client_id)
    if supplier_id is not None:
        filters.append(Equipment.supplier_id == supplier_id)
    if equipment_category is not None:
        filters.append(Equipment.equipment_category == equipment_category.value)
    if ownership is not None:
        filters.append(Equipment.ownership == ownership.value)
    if is_active is not None:
        filters.append(Equipment.is_active == is_active)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            Equipment.machine_code.ilike(pattern) | Equipment.machine_type.ilike(pattern)
        )

    count_stmt = select(func.count()).select_from(Equipment).where(*filters)
    total = session.execute(count_stmt).scalar_one()
    equipment_by_code = (
        select(Equipment)
        .where(*filters)
        .order_by(Equipment.machine_code)
        .limit(page.limit)
        .offset(page.offset)
    )
    rows = session.execute(equipment_by_code).scalars().all()
    return Page(
        items=[EquipmentRead.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=EquipmentRead, status_code=status.HTTP_201_CREATED)
def create_equipment(body: EquipmentCreate, session: Session = Depends(get_db)) -> EquipmentRead:
    equipment = Equipment(**body.model_dump(by_alias=True))
    session.add(equipment)
    _commit_or_conflict(session)
    session.refresh(equipment)
    return EquipmentRead.model_validate(equipment)


@router.get("/{equipment_id}", response_model=EquipmentRead)
def get_equipment(equipment_id: int, session: Session = Depends(get_db)) -> EquipmentRead:
    return EquipmentRead.model_validate(_get_or_404(equipment_id, session))


@router.put("/{equipment_id}", response_model=EquipmentRead)
def update_equipment(
    equipment_id: int,
    body: EquipmentCreate,
    session: Session = Depends(get_db),
) -> EquipmentRead:
    """Full replace: every field of the machine is sent."""
    equipment = _get_or_404(equipment_id, session)
    for field, value in body.model_dump(by_alias=True).items():
        setattr(equipment, field, value)
    _commit_or_conflict(session)
    session.refresh(equipment)
    return EquipmentRead.model_validate(equipment)


@router.delete("/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_equipment(equipment_id: int, session: Session = Depends(get_db)) -> None:
    session.delete(_get_or_404(equipment_id, session))
    session.commit()


def _get_or_404(equipment_id: int, session: Session) -> Equipment:
    equipment = session.get(Equipment, equipment_id)
    if equipment is None:
        raise api_error(404, "not_found", "Equipment not found", {"id": equipment_id})
    return equipment


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(409, "conflict", SAVE_FAILED_MESSAGE) from exc
