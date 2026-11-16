"""Pydantic v2 schemas for the purchase-order router plus the API-wide response
primitives shared across the supply + finance half (money serialization, the
pagination envelope, and the standard error body).

These primitives live here because ``schemas/orders.py`` is the first schema
module of this half; the sibling finance/verification/alerts schema modules
import them from here to stay DRY. They are pure Pydantic - no FastAPI, no
SQLAlchemy - so nothing downstream forms an import cycle.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints

from app.models.enums import PoDiscrepancyKind, PoDiscrepancyReason, PoStatus
from app.money import MoneyIn, MoneyStr

# --- Shared serialization primitives ---------------------------------------

# Money is stored as integer minor units (cents) and crosses the HTTP boundary
# as a fixed 2-decimal euro string (``MoneyStr``); inbound money is a euro string
# parsed to cents (``MoneyIn``). Both live in :mod:`app.money` and are re-exported
# here for the sibling finance/verification schema modules that import from here.
__all__ = ["MoneyIn", "MoneyStr", "RateStr"]

# Rates/fractions (VAT, percentages) are NOT money: they serialize as their plain
# decimal string, preserving the stored scale (e.g. ``0.0600``).
RateStr = Annotated[
    Decimal,
    PlainSerializer(lambda v: format(Decimal(v), "f"), return_type=str, when_used="json"),
]

ItemT = TypeVar("ItemT")

RECEIPT_COMMENT_MAX_LENGTH = 2000
ReceiptComment = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=RECEIPT_COMMENT_MAX_LENGTH),
]


class Page(BaseModel, Generic[ItemT]):
    """Standard list envelope: ``{items, total, limit, offset}``."""

    items: list[ItemT]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict] | None = None


class ErrorEnvelope(BaseModel):
    """Single error envelope for every non-2xx response: ``{"error": {...}}``."""

    error: ErrorBody


# --- Purchase-order request schemas ----------------------------------------


class PoLineCreate(BaseModel):
    """Unit price and VAT are copied from the product catalogue at creation; any
    client-sent ``unit_price`` / ``vat_rate`` is ignored (extra fields are dropped)."""

    product_id: int
    qty: int = Field(gt=0)


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    order_date: datetime.date
    expected_delivery_date: datetime.date
    delivery_address: str | None = None
    comment: str | None = None
    lines: list[PoLineCreate] = Field(min_length=1)


class PurchaseOrderUpdate(BaseModel):
    expected_delivery_date: datetime.date | None = None
    delivery_address: str | None = None
    comment: str | None = None


class PoReceiveLine(BaseModel):
    po_line_id: int
    qty_received: int = Field(gt=0)


class PoReceiveRequest(BaseModel):
    received: list[PoReceiveLine] = Field(min_length=1)
    acknowledge_over_receipt: bool = False
    # Issues seen at delivery ("2 boxes broken", "arrived a day late"); blank means none.
    comment: ReceiptComment | None = None


class PoCloseShortLine(BaseModel):
    po_line_id: int
    reason: PoDiscrepancyReason | None = None
    comment: ReceiptComment | None = None


class PoCloseShortRequest(BaseModel):
    """Close a pending PO with the quantities received so far; short lines may carry a note."""

    lines: list[PoCloseShortLine] = Field(default_factory=list)


# --- Purchase-order response schemas ---------------------------------------


class PurchaseOrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    # Embedded from the products join so the PO detail UI shows code/name, not #id.
    product_code: str
    product_name: str
    qty_ordered: int
    qty_received: int
    unit_price: MoneyStr
    vat_rate: RateStr
    line_ex_vat: MoneyStr
    line_vat: MoneyStr
    line_incl_vat: MoneyStr


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    supplier_id: int
    status: PoStatus
    order_date: datetime.date
    expected_delivery_date: datetime.date
    delivery_address: str | None
    comment: str | None
    total_ex_vat: MoneyStr
    total_vat: MoneyStr
    total_incl_vat: MoneyStr
    created_at: datetime.datetime
    lines: list[PurchaseOrderLineRead]


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    qty: int
    movement_type: str
    po_line_id: int | None
    dispatch_line_id: int | None
    reason: str | None
    created_at: datetime.datetime


class PoReceiveResult(BaseModel):
    order: PurchaseOrderRead
    movements: list[StockMovementRead]


class PoReceiptLineRead(BaseModel):
    product_code: str
    product_name: str
    qty_received: int


class PoReceiptRead(BaseModel):
    """One "Receive goods" action: who, when, what came in, and the comment."""

    id: int
    comment: str | None
    created_by_name: str | None
    created_at: datetime.datetime
    lines: list[PoReceiptLineRead]


class PoCancelResult(BaseModel):
    order: PurchaseOrderRead
    previous_status: PoStatus
    reversal_movements: list[StockMovementRead]


class PoDiscrepancyRead(BaseModel):
    """One line of the "Not received" log: a shortfall at short-close or an over-receipt."""

    id: int
    po_id: int
    order_no: str
    supplier_id: int
    supplier_name: str
    product_code: str
    product_name: str
    kind: PoDiscrepancyKind
    qty_ordered: int
    qty_received: int
    qty_difference: int
    reason: PoDiscrepancyReason | None
    comment: str | None
    created_by_name: str | None
    created_at: datetime.datetime


PoHistoryAction = Literal["created", "edited", "received", "closed_short", "cancelled"]


class PoHistoryLine(BaseModel):
    """One detail row of a history event, e.g. ("Chicken wrap", "received 10")."""

    label: str
    detail: str


class PoHistoryEvent(BaseModel):
    action: PoHistoryAction
    at: datetime.datetime
    user_name: str | None
    comment: str | None
    lines: list[PoHistoryLine]


class MenuOrderPlanLine(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    need_qty: int
    in_stock_qty: int
    on_order_qty: int
    to_order_qty: int
    unit_price: MoneyStr
    vat_rate: RateStr


class MenuOrderPlanSupplier(BaseModel):
    supplier_id: int
    supplier_name: str
    lines: list[MenuOrderPlanLine]


class MenuOrderPlan(BaseModel):
    """Per-supplier order proposal for the saved menus of one week's chosen delivery days."""

    year: int
    week: int
    day_names: list[str]
    days_without_menu: list[str]
    expected_delivery_date: datetime.date
    suppliers: list[MenuOrderPlanSupplier]
    # Menu products with no supplier: they cannot be ordered until one is set.
    lines_without_supplier: list[MenuOrderPlanLine]
