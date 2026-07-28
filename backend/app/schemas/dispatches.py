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
    week_start: datetime.date  # Monday of the ISO week (generated from delivery_date)
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
    # When set, only this category's lines are replaced; others stay intact.
    category_id: int | None = None


class DispatchCloneRequest(ApiModel):
    """Copy a saved dispatch day's planned lines onto another day (no stock effect)."""

    source_year: int = Field(ge=2020, le=2100)
    source_week: int = Field(ge=1, le=53)
    source_day_name: str
    target_year: int = Field(ge=2020, le=2100)
    target_week: int = Field(ge=1, le=53)
    target_day_name: str
    # Confirm-overwrite: false -> 409 {code:"exists"} when the target already has a
    # saved dispatch.
    overwrite: bool = False


class ConfirmRequest(ApiModel):
    force: bool = False


class ConfirmResult(ApiModel):
    dispatch_id: int
    status: DispatchStatus
    movements_created: int
