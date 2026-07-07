"""Fridge CRUD plus per-weekday delivery configuration."""

from __future__ import annotations

from fastapi import Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.husky.sync import effective_status_clause
from app.models.master import Fridge, FridgeDeliveryConfig
from app.schemas.masters import (
    DeliveryConfigItem,
    DeliveryConfigReplace,
    FridgeCreate,
    FridgeRead,
    FridgeUpdate,
    Page,
    PaginationParams,
    api_error,
    make_router,
    pagination,
)

router = make_router(prefix="/api/v1/fridges", tags=["fridges"])


def _get_or_404(fridge_id: int, session: Session) -> Fridge:
    fridge = session.get(Fridge, fridge_id)
    if fridge is None:
        raise api_error(404, "not_found", "Fridge not found", {"id": fridge_id})
    return fridge


@router.get("", response_model=Page[FridgeRead])
def list_fridges(
    page: PaginationParams = Depends(pagination),
    status: str | None = Query(
        default=None,
        description="Filter by effective status: active | inactive | cancelled | all "
        "(local_status override wins over Husky is_active).",
    ),
    session: Session = Depends(get_db),
) -> Page[FridgeRead]:
    count_stmt = select(func.count()).select_from(Fridge)
    stmt = select(Fridge)
    status_clause = effective_status_clause(Fridge, status)
    if status_clause is not None:
        count_stmt = count_stmt.where(status_clause)
        stmt = stmt.where(status_clause)
    total = session.execute(count_stmt).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(Fridge.friendly_name).limit(page.limit).offset(page.offset)
        )
        .scalars()
        .all()
    )
    return Page(
        items=[FridgeRead.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=FridgeRead, status_code=status.HTTP_201_CREATED)
def create_fridge(body: FridgeCreate, session: Session = Depends(get_db)) -> FridgeRead:
    fridge = Fridge(**body.model_dump())
    session.add(fridge)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "Husky id or friendly name already exists", None
        ) from exc
    session.refresh(fridge)
    return FridgeRead.model_validate(fridge)


@router.get("/{fridge_id}", response_model=FridgeRead)
def get_fridge(fridge_id: int, session: Session = Depends(get_db)) -> FridgeRead:
    return FridgeRead.model_validate(_get_or_404(fridge_id, session))


@router.put("/{fridge_id}", response_model=FridgeRead)
def update_fridge(
    fridge_id: int, body: FridgeUpdate, session: Session = Depends(get_db)
) -> FridgeRead:
    fridge = _get_or_404(fridge_id, session)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(fridge, field, value)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "Husky id or friendly name already exists", None
        ) from exc
    session.refresh(fridge)
    return FridgeRead.model_validate(fridge)


@router.delete("/{fridge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fridge(fridge_id: int, session: Session = Depends(get_db)) -> None:
    fridge = _get_or_404(fridge_id, session)
    session.delete(fridge)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "Fridge is referenced and cannot be deleted", {"id": fridge_id}
        ) from exc


@router.get("/{fridge_id}/delivery-config", response_model=list[DeliveryConfigItem])
def get_delivery_config(
    fridge_id: int, session: Session = Depends(get_db)
) -> list[DeliveryConfigItem]:
    _get_or_404(fridge_id, session)
    rows = list(
        session.execute(
            select(FridgeDeliveryConfig)
            .where(FridgeDeliveryConfig.fridge_id == fridge_id)
            .order_by(FridgeDeliveryConfig.weekday)
        )
        .scalars()
        .all()
    )
    return [DeliveryConfigItem.model_validate(row) for row in rows]


@router.put("/{fridge_id}/delivery-config", response_model=list[DeliveryConfigItem])
def replace_delivery_config(
    fridge_id: int,
    body: DeliveryConfigReplace,
    session: Session = Depends(get_db),
) -> list[DeliveryConfigItem]:
    _get_or_404(fridge_id, session)
    weekdays = [item.weekday for item in body.items]
    if len(weekdays) != len(set(weekdays)):
        raise api_error(
            422, "validation_error", "Duplicate weekday in delivery config", None
        )
    for existing in session.execute(
        select(FridgeDeliveryConfig).where(FridgeDeliveryConfig.fridge_id == fridge_id)
    ).scalars().all():
        session.delete(existing)
    session.flush()
    for item in body.items:
        session.add(
            FridgeDeliveryConfig(
                fridge_id=fridge_id,
                weekday=item.weekday,
                min_daily_qty=item.min_daily_qty,
                days_to_fill=item.days_to_fill,
            )
        )
    session.commit()
    return get_delivery_config(fridge_id, session)
