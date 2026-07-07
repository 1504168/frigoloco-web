"""Forecast run and product-score schemas."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import Field

from app.schemas.masters import ApiModel, Money


class ForecastRunRequest(ApiModel):
    delivery_date: datetime.date
    # None = every fridge that has a delivery config for the target weekday.
    fridge_ids: list[int] | None = None
    # Extensible model selector (only "moving_average_3w" today).
    model: str = "moving_average_3w"
    # Optional per-run parameter overrides merged into the run's params JSONB.
    params: dict[str, Any] | None = None


class ForecastSaveRequest(ApiModel):
    """Persist the ONE saved forecast for the (year, week, day_name) key."""

    year: int = Field(ge=2020, le=2100)
    week: int = Field(ge=1, le=53)
    day_name: str
    fridge_ids: list[int] | None = None
    model: str = "moving_average_3w"
    params: dict[str, Any] | None = None
    # Confirm-overwrite: false -> 409 {code:"exists"} when a saved run exists.
    overwrite: bool = False


class ForecastResultOut(ApiModel):
    fridge_id: int
    category_id: int
    forecast_qty: Money
    valid_days: int
    holiday_days: int


class ForecastRunOut(ApiModel):
    run_id: int
    delivery_date: datetime.date
    iso_year: int
    week_no: int
    day_name: str
    run_at: datetime.datetime
    model: str
    is_saved: bool
    params: dict[str, Any]
    results: list[ForecastResultOut]


class ForecastActualCell(ApiModel):
    """One fridge×category actual over the forecast's 3-week lookback window."""

    fridge_id: int
    category_id: int
    added_qty: int
    sold_qty: int
    # sold_qty / added_qty as a fraction (null when nothing was added).
    ratio: Money | None


class ForecastActualsOut(ApiModel):
    """Added/Sold/% side block: actuals over the same window as the forecast run."""

    year: int
    week: int
    day_name: str
    delivery_date: datetime.date
    window_start: datetime.date
    window_end: datetime.date  # exclusive (the delivery date itself)
    cells: list[ForecastActualCell]


class ScoreRecomputeRequest(ApiModel):
    # Defaults to today when omitted (trailing-365-day window ends here).
    as_of: datetime.date | None = None


class ScoreRecomputeResult(ApiModel):
    period_end: datetime.date
    products_scored: int


class ProductScoreOut(ApiModel):
    product_id: int
    period_end: datetime.date
    pct_sold: Money | None
    review_score: Money | None
    margin_score: Money | None
    final_score: Money
    sample_size: int
    computed_at: datetime.datetime
