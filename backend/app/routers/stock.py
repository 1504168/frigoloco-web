"""Stock balances, adjustments and movement ledger (R6)."""

from __future__ import annotations

from fastapi import Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.masters import Page, PaginationParams, make_router, pagination
from app.schemas.stock import (
    AdjustmentRequest,
    MovementOut,
    MovementsPage,
    OpeningStockRequest,
    StockBalanceOut,
)
from app.services import stock_service
from app.services.stock_service import StockBalancesQuery

router = make_router(prefix="/api/v1/stock", tags=["stock"])


@router.get("/balances", response_model=Page[StockBalanceOut])
def list_balances(
    page: PaginationParams = Depends(pagination),
    search: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> Page[StockBalanceOut]:
    rows, total = stock_service.list_balances(
        StockBalancesQuery(search=search), page, session
    )
    return Page(
        items=[
            StockBalanceOut(
                product_id=row.product_id,
                product_code=row.product_code,
                product_name=row.product_name,
                physical_qty=int(row.physical_qty),
                on_order_qty=int(row.on_order_qty),
                available_qty=int(row.available_qty),
            )
            for row in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/adjustments", response_model=MovementOut, status_code=status.HTTP_201_CREATED
)
def create_adjustment(
    body: AdjustmentRequest, session: Session = Depends(get_db)
) -> MovementOut:
    movement = stock_service.record_adjustment(
        product_id=body.product_id,
        qty=body.qty,
        reason=body.reason,
        user_id=None,
        session=session,
    )
    return MovementOut.model_validate(movement)


@router.post(
    "/opening-stock", response_model=MovementOut, status_code=status.HTTP_201_CREATED
)
def record_opening_stock(
    body: OpeningStockRequest, session: Session = Depends(get_db)
) -> MovementOut:
    """Seed a product's opening stock (positive adjustment, reason mandatory)."""
    movement = stock_service.record_opening_stock(
        product_id=body.product_id,
        qty=body.qty,
        reason=body.reason,
        user_id=None,
        session=session,
    )
    return MovementOut.model_validate(movement)


@router.get("/movements", response_model=MovementsPage)
def list_movements(
    after_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    product_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MovementsPage:
    rows, next_after_id = stock_service.list_movements(
        product_id=product_id, after_id=after_id, limit=limit, session=session
    )
    return MovementsPage(
        items=[MovementOut.model_validate(row) for row in rows],
        limit=limit,
        after_id=after_id,
        next_after_id=next_after_id,
    )
