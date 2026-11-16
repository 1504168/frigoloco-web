"""Weekly menu, product-target, menu-cap and allocation schemas."""

from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import Field

from app.models.enums import MenuStatus
from app.money import MoneyStr
from app.schemas.masters import ApiModel, ClientRuleViolation


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


class TargetProductOut(ApiModel):
    product_id: int
    product_code: str
    product_name: str


class TargetCategoryOut(ApiModel):
    """An active Snacks or Drinks category and its active products, in name order."""

    category_id: int
    category_name: str
    products: list[TargetProductOut]


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
    # True when the line was computed from a stale/absent fridge_stock generation
    # (the snapshot job is behind): the quantity still uses the last-known units.
    stock_stale: bool = False
    # True when the product had no score and weighed its category's mean score.
    default_score: bool = False


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


class WeekMenuOut(ApiModel):
    """The products chosen for an ISO week, per category; ``menu_id`` None when unsaved."""

    menu_id: int | None
    year: int
    week: int
    categories: list[MenuGridCategoryOut]


class MenuImportRequest(ApiModel):
    # The products on screen; None = use the saved week menu.
    product_ids: list[int] | None = None
    # Refill products sold since the fridge's last delivery first (off for a fresh Monday).
    sold_first: bool = False
    # Give each product only what it needs beyond its good units in the fridge.
    use_fridge_stock: bool = False
    # Scale a fridge x category up or down by how fast it sells against its last forecast.
    sales_speed: bool = False
    # Cut each product to the physical warehouse stock, proportionally per fridge.
    fit_to_stock: bool = False


class MenuStockCutOut(ApiModel):
    """Good units a product already has in a fridge and how much they cut its import."""

    fridge_id: int
    product_id: int
    in_fridge_units: int
    reduced_by: int


class SalesSpeedAdjustmentOut(ApiModel):
    """A fridge x category forecast scaled by its sales speed since the last delivery."""

    fridge_id: int
    category_id: int
    # The previous delivery's forecast for the time until the next delivery.
    forecast_units: Decimal
    sold_units: int
    # Forecast units the hourly profile still expects until the next delivery.
    remaining_units: Decimal
    # (sold + remaining) / forecast, and the multiplier applied (both 2 decimals).
    pace: Decimal
    factor: Decimal
    # Whose hourly sales shaped the profile: "fridge", "category" or "linear".
    profile_source: str


class ShelfLifeHoldOut(ApiModel):
    """A product a sales-speed raise skipped: it would expire before the coverage end."""

    fridge_id: int
    product_id: int
    raised_qty: int
    kept_qty: int
    shelf_life_days: int
    coverage_days: int


class WarehouseStockCutOut(ApiModel):
    """A product the fridges asked more of than the warehouse holds, and how much was cut."""

    product_id: int
    requested: int
    in_stock: int
    cut: int


class MenuImportOut(ApiModel):
    grid: MenuGridOut
    # True when nothing was chosen for the imported scope, so products came from ratings.
    used_rating_suggestion: bool
    # Forecast categories that got nothing because the week menu has no product in them.
    categories_without_products: list[int]
    sold_first: bool
    fridge_stock_applied: bool = False
    # Fridges whose stock reading is missing or older than the allocation's max age.
    stale_stock_fridge_ids: list[int] = Field(default_factory=list)
    stock_cuts: list[MenuStockCutOut] = Field(default_factory=list)
    sales_speed_adjustments: list[SalesSpeedAdjustmentOut] = Field(default_factory=list)
    shelf_life_holds: list[ShelfLifeHoldOut] = Field(default_factory=list)
    # Products without a score that got units, split with their category's mean score.
    default_score_product_ids: list[int] = Field(default_factory=list)
    warehouse_stock_cuts: list[WarehouseStockCutOut] = Field(default_factory=list)
    # Fridges whose Snacks and Drinks were refilled to their targets.
    target_refill_fridge_ids: list[int] = Field(default_factory=list)
    # Imported cells whose client excludes one of the product's tags: a warning, never a block.
    rule_violations: list[ClientRuleViolation] = Field(default_factory=list)


class MenuStockBalanceOut(ApiModel):
    product_id: int
    in_stock_qty: int
    on_order_qty: int


class MenuDraftLineOut(ApiModel):
    product_id: int
    code: str
    name: str
    qty: int
    unit_price: MoneyStr  # cents in, euro string out
    vat_rate: Decimal


class MenuLineItem(ApiModel):
    fridge_id: int
    product_id: int
    qty: int = Field(ge=0)


class MenuSaveRequest(ApiModel):
    year: int = Field(ge=2020, le=2100)
    week: int = Field(ge=1, le=53)
    day_name: str
    lines: list[MenuLineItem]
    # Confirm-overwrite: false -> 409 {code:"exists"} when a saved menu (or, when
    # category_id is set, that category) already has saved lines.
    overwrite: bool = False
    # When set, only this category's lines are replaced; others stay intact.
    category_id: int | None = None
