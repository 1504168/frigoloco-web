"""Purchase-order endpoints (R4/R5): create, read, edit, draft-from-dispatch,
receive, cancel. Routers stay thin — validation + delegation only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import PoStatus
from app.schemas.orders import (
    Page,
    PoCancelResult,
    PoReceiveRequest,
    PoReceiveResult,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
)
from app.services import orders_service
from app.services.orders_service import (
    PageParams,
    ReceiptLine,
    envelope,
    get_page_params,
)

router = APIRouter(prefix="/api/v1/purchase-orders", tags=["purchase-orders"])


@router.get("", response_model=Page[PurchaseOrderRead])
@envelope
def list_purchase_orders(
    status: PoStatus | None = None,
    supplier_id: int | None = None,
    page: PageParams = Depends(get_page_params),
    db: Session = Depends(get_db),
) -> Page[PurchaseOrderRead]:
    items, total = orders_service.list_purchase_orders(
        db, page, status=status, supplier_id=supplier_id
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=PurchaseOrderRead, status_code=201)
@envelope
def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
) -> PurchaseOrderRead:
    return orders_service.create_purchase_order(db, payload)


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
) -> PurchaseOrderRead:
    return orders_service.update_purchase_order(db, po_id, payload)


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
) -> PoReceiveResult:
    order, movements = orders_service.receive_purchase_order(
        db,
        po_id,
        [ReceiptLine(r.po_line_id, r.qty_received) for r in payload.received],
        payload.acknowledge_over_receipt,
    )
    return PoReceiveResult(order=order, movements=movements)


@router.post("/{po_id}/cancel", response_model=PoCancelResult)
@envelope
def cancel_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
) -> PoCancelResult:
    order, previous, reversals = orders_service.cancel_purchase_order(db, po_id)
    return PoCancelResult(
        order=order, previous_status=previous, reversal_movements=reversals
    )
