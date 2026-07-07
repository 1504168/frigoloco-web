"""Pydantic v2 schemas for the purchase-order router plus the API-wide response
primitives shared across the supply + finance half (money serialization, the
pagination envelope, and the standard error body).

These primitives live here because ``schemas/orders.py`` is the first schema
module of this half; the sibling finance/verification/alerts schema modules
import them from here to stay DRY. They are pure Pydantic — no FastAPI, no
SQLAlchemy — so nothing downstream forms an import cycle.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models.enums import PoStatus
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
    product_id: int
    qty: int = Field(gt=0)
    # Euro string on the wire -> integer cents (MoneyIn). ge=0 checks the cents.
    unit_price: MoneyIn = Field(ge=0)
    vat_rate: Decimal = Field(ge=0, lt=1)


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


class PoCancelResult(BaseModel):
    order: PurchaseOrderRead
    previous_status: PoStatus
    reversal_movements: list[StockMovementRead]
