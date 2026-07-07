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
    """Keyset page for the high-volume movements ledger (``?after_id=``)."""

    items: list[MovementOut]
    limit: int
    after_id: int | None
    next_after_id: int | None
