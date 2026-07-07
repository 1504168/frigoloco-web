"""Product catalogue schemas, including per-fridge price overrides."""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import Field

from app.money import MoneyIn, MoneyStr
from app.schemas.masters import ApiModel, Money

# Manual status override (D5): NULL follows Husky, else user-forced.
LocalStatus = Literal["inactive", "cancelled"]


class ProductCreate(ApiModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category_id: int
    supplier_id: int | None = None
    # Prices: euro string -> cents (MoneyIn). vat_rate is a fraction, not money.
    purchase_price: MoneyIn = Field(default=0, ge=0)
    sales_price: MoneyIn = Field(default=0, ge=0)
    vat_rate: Money = Field(default=0, ge=0, lt=1)  # type: ignore[valid-type]
    shelf_life_days: int | None = Field(default=None, gt=0)
    is_active: bool = True
    local_status: LocalStatus | None = None


class ProductUpdate(ApiModel):
    code: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1)
    category_id: int | None = None
    supplier_id: int | None = None
    purchase_price: MoneyIn | None = Field(default=None, ge=0)
    sales_price: MoneyIn | None = Field(default=None, ge=0)
    vat_rate: Money | None = Field(default=None, ge=0, lt=1)  # type: ignore[valid-type]
    shelf_life_days: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    # Explicit null clears the override (follow Husky again); omitted = unchanged.
    local_status: LocalStatus | None = None


class ProductRead(ApiModel):
    id: int
    code: str
    name: str
    category_id: int
    supplier_id: int | None
    purchase_price: MoneyStr
    sales_price: MoneyStr
    vat_rate: Money
    shelf_life_days: int | None
    is_active: bool
    local_status: LocalStatus | None
    # Effective status = local_status if set, else active/inactive from is_active.
    effective_status: str
    husky_synced_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class FridgePriceItem(ApiModel):
    fridge_id: int
    sales_price: MoneyIn = Field(ge=0)


class FridgePriceRead(ApiModel):
    fridge_id: int
    product_id: int
    sales_price: MoneyStr
    updated_at: datetime.datetime


class FridgePriceReplace(ApiModel):
    items: list[FridgePriceItem]
