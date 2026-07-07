"""Dispatch batch, line-editing, matrix and confirm schemas."""

from __future__ import annotations

import datetime

from pydantic import Field

from app.models.enums import DispatchStatus, LineSource
from app.schemas.masters import ApiModel


class DispatchCreate(ApiModel):
    delivery_date: datetime.date


class DispatchRead(ApiModel):
    id: int
    delivery_date: datetime.date
    iso_week: int
    weekday: int
    status: DispatchStatus
    confirmed_by: int | None
    confirmed_at: datetime.datetime | None
    created_by: int | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class DispatchLineItem(ApiModel):
    fridge_id: int
    product_id: int
    qty: int = Field(gt=0)
    source: LineSource = LineSource.manual


class DispatchLinesReplace(ApiModel):
    lines: list[DispatchLineItem]


class MatrixFridge(ApiModel):
    fridge_id: int
    friendly_name: str


class MatrixProduct(ApiModel):
    product_id: int
    product_name: str
    category_id: int


class MatrixCell(ApiModel):
    fridge_id: int
    product_id: int
    qty: int


class MatrixCategory(ApiModel):
    category_id: int
    category_name: str
    product_ids: list[int]


class DispatchMatrix(ApiModel):
    dispatch_id: int
    fridges: list[MatrixFridge]
    products: list[MatrixProduct]
    categories: list[MatrixCategory]
    cells: list[MatrixCell]


class DispatchSaveRequest(ApiModel):
    """Save a PLANNED dispatch keyed on (year, week, day_name); overwrite-confirm."""

    year: int = Field(ge=2020, le=2100)
    week: int = Field(ge=1, le=53)
    day_name: str
    lines: list[DispatchLineItem]
    overwrite: bool = False


class ConfirmRequest(ApiModel):
    force: bool = False


class ConfirmResult(ApiModel):
    dispatch_id: int
    status: DispatchStatus
    movements_created: int
