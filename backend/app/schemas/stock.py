"""Stock balance, adjustment and movement schemas."""

from __future__ import annotations

import datetime

from pydantic import Field, field_validator

from app.models.enums import StockMovementType
from app.schemas.masters import ApiModel


class StockBalanceOut(ApiModel):
    product_id: int
    product_code: str
    product_name: str
    physical_qty: int
    on_order_qty: int
    available_qty: int
    category_id: int
    category_name: str
    supplier_id: int | None
    supplier_name: str | None
    # Warehouse minimum; null = no minimum set.
    min_stock_qty: int | None
    # True when the warehouse holds fewer units than min_stock_qty.
    is_low_stock: bool
    # Units in all fridges from the latest Husky stock reading.
    fridge_units: int
    is_active: bool


class MinimumStockRequest(ApiModel):
    """Warehouse minimum of one product; null removes it (no low-stock alert)."""

    min_stock_qty: int | None = Field(ge=0)


class MinimumStockOut(ApiModel):
    product_id: int
    min_stock_qty: int | None
    physical_qty: int
    is_low_stock: bool


class AdjustmentRequest(ApiModel):
    product_id: int
    # Signed, non-zero. The DB CHECK also enforces qty <> 0.
    qty: int
    reason: str = Field(min_length=1)

    @field_validator("qty")
    @classmethod
    def _qty_nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("qty must be non-zero")
        return value

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason is mandatory and cannot be blank")
        return stripped


class OpeningStockRequest(ApiModel):
    """Opening-stock take: a positive, reason-mandatory adjustment (D2)."""

    product_id: int
    qty: int = Field(gt=0)
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason is mandatory and cannot be blank")
        return stripped


class MovementOut(ApiModel):
    id: int
    product_id: int
    qty: int
    movement_type: StockMovementType
    po_line_id: int | None
    dispatch_line_id: int | None
    reason: str | None
    created_by: int | None
    created_at: datetime.datetime


class MovementsPage(ApiModel):
    """Keyset page of the movements ledger, newest first (``?before_id=``)."""

    items: list[MovementOut]
    limit: int
    before_id: int | None
    next_before_id: int | None


class FridgeUnitsOut(ApiModel):
    """Units of one product in one fridge, from the latest Husky stock reading."""

    fridge_id: int
    fridge_name: str
    units: int
    next_expiry_at: datetime.datetime | None
    taken_at: datetime.datetime
    is_stale: bool


class SameNameProductOut(ApiModel):
    """Another product with the same name, e.g. an old short code next to today's EAN."""

    product_id: int
    product_code: str
    is_active: bool
    fridge_units: int


class ProductLocationsOut(ApiModel):
    """Where a product is right now: every fridge holding it plus the warehouse."""

    product_id: int
    product_code: str
    product_name: str
    physical_qty: int
    on_order_qty: int
    available_qty: int
    fridge_units_total: int
    latest_taken_at: datetime.datetime | None
    fridges: list[FridgeUnitsOut]
    is_active: bool
    same_name_products: list[SameNameProductOut]
