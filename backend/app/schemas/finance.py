"""Pydantic v2 schemas for the finance router (R10/R11/R12)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.money import MoneyIn
from app.schemas.orders import MoneyStr, RateStr


class WeeklyFinancialInputs(BaseModel):
    """Manual weekly entries (R10). Money arrives as euro strings -> cents."""

    catering_turnover: MoneyIn = Field(default=0, ge=0)
    catering_food_cost: MoneyIn = Field(default=0, ge=0)
    tgtg_turnover: MoneyIn = Field(default=0, ge=0)
    logistics_cost: MoneyIn = Field(default=0, ge=0)
    drops_count: int = Field(default=0, ge=0)
    unsold_items: int = Field(default=0, ge=0)
    fridge_count: int | None = Field(default=None, ge=0)
    remarks: str | None = None


class WeeklyInputsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    catering_turnover: MoneyStr
    catering_food_cost: MoneyStr
    tgtg_turnover: MoneyStr
    logistics_cost: MoneyStr
    drops_count: int
    unsold_items: int
    fridge_count: int | None
    remarks: str | None


class WeeklyPnlRead(BaseModel):
    year: int
    iso_week: int
    week_start: datetime.date
    inputs: WeeklyInputsRead
    # Computed KPIs (R10).
    gross_sales: MoneyStr
    refunds: MoneyStr
    customer_credit: MoneyStr
    frigoloco_discounts: MoneyStr
    items_sold: int
    turnover_ex_vat: MoneyStr
    fridge_food_cost_added: MoneyStr
    pos_fee_pct: RateStr
    rfid_fee_rate: MoneyStr
    pos_fee: MoneyStr
    rfid_fee: MoneyStr
    net_margin: MoneyStr


class MonthlyAnalysisRow(BaseModel):
    key_id: int | None
    key_name: str
    food_margin: MoneyStr
    rfid_fee: MoneyStr | None = None
    sales: MoneyStr | None = None
    pos_fee: MoneyStr | None = None
    fee_share: MoneyStr | None = None
    service_additionals: MoneyStr | None = None
    logistics_share: MoneyStr | None = None
    net_margin: MoneyStr


class MonthlyAnalysisRead(BaseModel):
    month: str
    dimension: str
    rows: list[MonthlyAnalysisRow]


class FridgeReportRow(BaseModel):
    """One product line of the fridge report."""

    product_id: int
    code: str
    name: str
    category: str | None
    added_qty: int
    unit_buying_price: MoneyStr
    unit_selling_price: MoneyStr


class FridgeReportRead(BaseModel):
    fridge_id: int
    date_from: datetime.date
    date_to: datetime.date
    # Summary KPIs.
    added_qty: int  # total added qty across all products
    food_cost: MoneyStr
    revenue: MoneyStr
    margin: MoneyStr  # food margin in euros
    margin_pct: RateStr | None = None  # food margin as a 0..1 fraction of ex-VAT revenue
    # Per-product breakdown.
    rows: list[FridgeReportRow] = []
