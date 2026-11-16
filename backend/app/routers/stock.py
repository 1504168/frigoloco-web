"""Stock balances, adjustments and movement ledger (R6)."""

from __future__ import annotations

import httpx
from fastapi import Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.husky.client import RetryableHuskyError
from app.husky.sync import HUSKY_NOT_CONFIGURED_MESSAGE, is_husky_configured, snapshot_stock
from app.models.master import User
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.schemas.stock import (
    AdjustmentRequest,
    MinimumStockOut,
    MinimumStockRequest,
    MovementOut,
    MovementsPage,
    OpeningStockRequest,
    ProductLocationsOut,
    StockBalanceOut,
)
from app.security import get_current_user
from app.services import low_stock_service, product_location_service, stock_service
from app.services.low_stock_service import is_below_minimum_stock
from app.services.stock_service import StockBalancesQuery

router = make_router(prefix="/api/v1/stock", tags=["stock"])


@router.get("/balances", response_model=Page[StockBalanceOut])
def list_balances(
    page: PaginationParams = Depends(pagination),
    search: str | None = Query(
        default=None,
        description="Case-insensitive contains match on product code or name.",
    ),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    include_inactive: bool = Query(
        default=False,
        description="Also list inactive products with no stock (old codes from history).",
    ),
    session: Session = Depends(get_db),
) -> Page[StockBalanceOut]:
    balances_query = StockBalancesQuery(
        search=search,
        category_id=category_id,
        supplier_id=supplier_id,
        include_inactive=include_inactive,
    )
    rows, total = stock_service.list_balances(balances_query, page, session)
    return Page(
        items=[
            StockBalanceOut(
                product_id=row.product_id,
                product_code=row.product_code,
                product_name=row.product_name,
                physical_qty=int(row.physical_qty),
                on_order_qty=int(row.on_order_qty),
                available_qty=int(row.available_qty),
                category_id=row.category_id,
                category_name=row.category_name,
                supplier_id=row.supplier_id,
                supplier_name=row.supplier_name,
                min_stock_qty=row.min_stock_qty,
                is_low_stock=is_below_minimum_stock(int(row.physical_qty), row.min_stock_qty),
                fridge_units=int(row.fridge_units),
                is_active=row.is_active,
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
    body: AdjustmentRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MovementOut:
    movement = stock_service.record_adjustment(
        product_id=body.product_id,
        qty=body.qty,
        reason=body.reason,
        user_id=current_user.id,
        session=session,
    )
    return MovementOut.model_validate(movement)


@router.post(
    "/opening-stock", response_model=MovementOut, status_code=status.HTTP_201_CREATED
)
def record_opening_stock(
    body: OpeningStockRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MovementOut:
    """Seed a product's opening stock (positive adjustment, reason mandatory)."""
    movement = stock_service.record_opening_stock(
        product_id=body.product_id,
        qty=body.qty,
        reason=body.reason,
        user_id=current_user.id,
        session=session,
    )
    return MovementOut.model_validate(movement)


@router.get("/movements", response_model=MovementsPage)
def list_movements(
    before_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    product_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MovementsPage:
    """Movements newest first; pass ``next_before_id`` as ``before_id`` for older ones."""
    rows, next_before_id = stock_service.list_movements(
        product_id=product_id,
        before_id=before_id,
        limit=limit,
        session=session,
    )
    return MovementsPage(
        items=[MovementOut.model_validate(row) for row in rows],
        limit=limit,
        before_id=before_id,
        next_before_id=next_before_id,
    )


@router.put("/products/{product_id}/minimum", response_model=MinimumStockOut)
def set_minimum_stock(
    product_id: int,
    body: MinimumStockRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MinimumStockOut:
    """Set the warehouse minimum (null removes it); low-stock alerts update at once."""
    update = low_stock_service.set_minimum_stock(
        product_id=product_id,
        min_stock_qty=body.min_stock_qty,
        user_id=current_user.id,
        session=session,
    )
    return MinimumStockOut(
        product_id=update.product_id,
        min_stock_qty=update.min_stock_qty,
        physical_qty=update.physical_qty,
        is_low_stock=update.is_low_stock,
    )


@router.get("/products/{product_id}/fridges", response_model=ProductLocationsOut)
def get_product_locations(
    product_id: int,
    session: Session = Depends(get_db),
) -> ProductLocationsOut:
    """Units of one product in every fridge (latest 15-min snapshot) plus the warehouse."""
    return product_location_service.get_product_locations(product_id, session)


@router.post("/products/{product_id}/fridges/refresh", response_model=ProductLocationsOut)
def refresh_product_locations(
    product_id: int,
    session: Session = Depends(get_db),
) -> ProductLocationsOut:
    """Re-read live fridge stock from Husky (5 to 10 s), then return the product's locations."""
    if not is_husky_configured():
        raise api_error(503, "husky_not_configured", HUSKY_NOT_CONFIGURED_MESSAGE)
    try:
        snapshot_stock()
    except (httpx.HTTPError, RetryableHuskyError) as exc:
        raise api_error(
            502,
            "husky_unavailable",
            "Could not read live fridge stock from Husky",
        ) from exc
    return product_location_service.get_product_locations(product_id, session)
