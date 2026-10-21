"""Forecast run and product-score schemas."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.schemas.masters import ApiModel, Money
from app.services.forecast.strategies import DEFAULT_STRATEGY_CODE
from app.services.scoring_service import YEARLY_SCORE_WINDOW_DAYS, ScoreWindowDays

# forecast_results.forecast_qty is NUMERIC(10,2).
MAX_FORECAST_QTY = Decimal("99999999.99")


class ForecastRunRequest(ApiModel):
    delivery_date: datetime.date
    # None = every fridge that has a delivery config for the target weekday.
    fridge_ids: list[int] | None = None
    # Forecast method code, one of GET /forecasts/models.
    model: str = DEFAULT_STRATEGY_CODE
    # Optional per-run parameter overrides merged into the run's params JSONB.
    params: dict[str, Any] | None = None


class ForecastCellEdit(ApiModel):
    """One fridge x category quantity exactly as shown (and possibly edited) on screen."""

    fridge_id: int
    category_id: int
    forecast_qty: Decimal = Field(ge=0, le=MAX_FORECAST_QTY)


class ForecastSaveRequest(ApiModel):
    """Save a computed run as the ONE saved forecast for its delivery date."""

    run_id: int
    cells: list[ForecastCellEdit]
    # Confirm-overwrite: false -> 409 {code:"exists"} when a saved run exists.
    overwrite: bool = False


class ForecastModelOut(ApiModel):
    code: str
    label: str


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
    window_start: datetime.date
    window_end: datetime.date  # exclusive
    # Units sold in the window by the run's fridges; 0 means the window has no data.
    window_sales_units: int
    # Categories with no active product and no sales in the window.
    hidden_category_ids: list[int]
    # False when the delivery date is not the next one, so current fridge stock was not deducted.
    residual_applied: bool


class ForecastActualCell(ApiModel):
    """One fridge x category actual over the forecast method's sales window."""

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
    window_end: datetime.date  # exclusive
    cells: list[ForecastActualCell]


class ScoreRecomputeRequest(ApiModel):
    # Defaults to today when omitted (the trailing window ends here).
    as_of: datetime.date | None = None
    window_days: ScoreWindowDays = YEARLY_SCORE_WINDOW_DAYS


class ScoreRecomputeResult(ApiModel):
    period_end: datetime.date
    window_days: int
    products_scored: int


class ProductScoreOut(ApiModel):
    product_id: int
    period_end: datetime.date
    pct_sold: Money | None
    review_score: Money | None
    margin_score: Money | None
    final_score: Money
    sample_size: int
    window_days: int
    sold_qty: int | None
    positive_reviews: int | None
    negative_reviews: int | None
    uses_new_product_baseline: bool
    computed_at: datetime.datetime
