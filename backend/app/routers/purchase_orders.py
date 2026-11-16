"""Purchase-order endpoints (R4/R5): create, read, edit, draft-from-dispatch,
receive, close short, cancel, history, the "Not received" log and the menu order
plan. Routers stay thin - validation + delegation only."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import PoDiscrepancyKind, PoStatus
from app.models.master import User
from app.schemas.orders import (
    MenuOrderPlan,
    Page,
    PoCancelResult,
    PoCloseShortRequest,
    PoDiscrepancyRead,
    PoHistoryEvent,
    PoReceiptRead,
    PoReceiveRequest,
    PoReceiveResult,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
)
from app.security import get_current_user
from app.services import orders_service
from app.services.orders_service import (
    PageParams,
    ReceiptLine,
    ShortLineNote,
    envelope,
    get_page_params,
)

router = APIRouter(prefix="/api/v1/purchase-orders", tags=["purchase-orders"])


@router.get("", response_model=Page[PurchaseOrderRead])
@envelope
def list_purchase_orders(
    status: PoStatus | None = None,
    supplier_id: int | None = None,
    delivery_from: datetime.date | None = None,
    delivery_to: datetime.date | None = None,
    search: str | None = Query(
        default=None,
        description="Case-insensitive contains match on order number or supplier name.",
    ),
    page: PageParams = Depends(get_page_params),
    db: Session = Depends(get_db),
) -> Page[PurchaseOrderRead]:
    items, total = orders_service.list_purchase_orders(
        db,
        page,
        status=status,
        supplier_id=supplier_id,
        delivery_from=delivery_from,
        delivery_to=delivery_to,
        search=search,
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=PurchaseOrderRead, status_code=201)
@envelope
def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PurchaseOrderRead:
    return orders_service.create_purchase_order(db, payload, user_id=current_user.id)


@router.get("/discrepancies", response_model=Page[PoDiscrepancyRead])
@envelope
def list_purchase_order_discrepancies(
    kind: PoDiscrepancyKind | None = None,
    supplier_id: int | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    page: PageParams = Depends(get_page_params),
    db: Session = Depends(get_db),
) -> Page[PoDiscrepancyRead]:
    items, total = orders_service.list_purchase_order_discrepancies(
        db,
        page,
        kind=kind,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/menu-order-plan", response_model=MenuOrderPlan)
@envelope
def get_menu_order_plan(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_names: list[str] = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> MenuOrderPlan:
    return orders_service.build_menu_order_plan(
        db,
        year=year,
        week=week,
        day_names=day_names,
    )


@router.get("/{po_id}", response_model=PurchaseOrderRead)
@envelope
def get_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
) -> PurchaseOrderRead:
    return orders_service.get_purchase_order(db, po_id)


@router.patch("/{po_id}", response_model=PurchaseOrderRead)
@envelope
def update_purchase_order(
    po_id: int,
    payload: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PurchaseOrderRead:
    return orders_service.update_purchase_order(db, po_id, payload, user_id=current_user.id)


@router.post("/{dispatch_id}/draft-from-dispatch", response_model=list[PurchaseOrderRead])
@envelope
def draft_from_dispatch(
    dispatch_id: int,
    db: Session = Depends(get_db),
) -> list[PurchaseOrderRead]:
    return orders_service.draft_purchase_orders_from_dispatch(db, dispatch_id)


@router.post("/{po_id}/receive", response_model=PoReceiveResult)
@envelope
def receive_purchase_order(
    po_id: int,
    payload: PoReceiveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PoReceiveResult:
    order, movements = orders_service.receive_purchase_order(
        db,
        po_id,
        [ReceiptLine(r.po_line_id, r.qty_received) for r in payload.received],
        payload.acknowledge_over_receipt,
        comment=payload.comment,
        user_id=current_user.id,
    )
    return PoReceiveResult(order=order, movements=movements)


@router.get("/{po_id}/receipts", response_model=list[PoReceiptRead])
@envelope
def list_purchase_order_receipts(
    po_id: int,
    db: Session = Depends(get_db),
) -> list[PoReceiptRead]:
    return orders_service.list_purchase_order_receipts(db, po_id)


@router.get("/{po_id}/history", response_model=list[PoHistoryEvent])
@envelope
def get_purchase_order_history(
    po_id: int,
    db: Session = Depends(get_db),
) -> list[PoHistoryEvent]:
    return orders_service.get_purchase_order_history(db, po_id)


@router.post("/{po_id}/close-short", response_model=PurchaseOrderRead)
@envelope
def close_purchase_order_short(
    po_id: int,
    payload: PoCloseShortRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PurchaseOrderRead:
    notes = [
        ShortLineNote(
            po_line_id=line.po_line_id,
            reason=line.reason,
            comment=line.comment or None,
        )
        for line in payload.lines
    ]
    return orders_service.close_purchase_order_short(
        db,
        po_id,
        notes,
        user_id=current_user.id,
    )


@router.post("/{po_id}/cancel", response_model=PoCancelResult)
@envelope
def cancel_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PoCancelResult:
    order, previous, reversals = orders_service.cancel_purchase_order(
        db, po_id, user_id=current_user.id
    )
    return PoCancelResult(
        order=order, previous_status=previous, reversal_movements=reversals
    )
