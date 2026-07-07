"""Weekly menu, product-target, menu-cap and allocation schemas."""

from __future__ import annotations

import datetime

from pydantic import Field

from app.models.enums import MenuStatus
from app.schemas.masters import ApiModel


class MenuRead(ApiModel):
    id: int
    year: int
    iso_week: int
    status: MenuStatus
    copied_from_id: int | None
    created_by: int | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class MenuProductsReplace(ApiModel):
    product_ids: list[int]


class TargetItem(ApiModel):
    product_id: int
    target_qty: int = Field(ge=0)


class TargetsReplace(ApiModel):
    items: list[TargetItem]


class TargetRead(ApiModel):
    fridge_id: int
    product_id: int
    target_qty: int
    updated_at: datetime.datetime


class CapItem(ApiModel):
    product_id: int
    max_qty: int = Field(gt=0)


class CapsReplace(ApiModel):
    items: list[CapItem]


class CapRead(ApiModel):
    fridge_id: int
    product_id: int
    max_qty: int
    updated_at: datetime.datetime


class AllocationLineOut(ApiModel):
    fridge_id: int
    category_id: int
    product_id: int
    qty: int
    source: str


class AllocateResponse(ApiModel):
    menu_id: int
    forecast_run_id: int
    lines: list[AllocationLineOut]


# --- Workflow menu grid (D2) -----------------------------------------------


class MenuGridFridgeOut(ApiModel):
    fridge_id: int
    friendly_name: str


class MenuGridProductOut(ApiModel):
    product_id: int
    product_name: str
    category_id: int


class MenuGridCategoryOut(ApiModel):
    category_id: int
    category_name: str
    product_ids: list[int]


class MenuGridCellOut(ApiModel):
    fridge_id: int
    product_id: int
    qty: int


class MenuGridOut(ApiModel):
    """Category-banded fridge x product grid keyed on (year, week, day_name)."""

    menu_id: int | None
    year: int
    week: int
    day_name: str
    fridges: list[MenuGridFridgeOut]
    products: list[MenuGridProductOut]
    categories: list[MenuGridCategoryOut]
    cells: list[MenuGridCellOut]


class MenuLineItem(ApiModel):
    fridge_id: int
    product_id: int
    qty: int = Field(ge=0)


class MenuSaveRequest(ApiModel):
    year: int = Field(ge=2020, le=2100)
    week: int = Field(ge=1, le=53)
    day_name: str
    lines: list[MenuLineItem]
    # Confirm-overwrite: false -> 409 {code:"exists"} when a saved menu exists.
    overwrite: bool = False
