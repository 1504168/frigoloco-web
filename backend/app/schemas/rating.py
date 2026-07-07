"""Schemas for the product rating scorecard (D3).

The scorecard exposes every Excel-equivalent column per product plus the live
scoring weights in the page envelope, so the UI can render the full rating grid
and show how the final score is weighted.
"""

from __future__ import annotations

import datetime

from pydantic import BaseModel

from app.schemas.masters import Money
from app.schemas.orders import MoneyStr, RateStr


class ScorecardWeights(BaseModel):
    """The live ``scoring_weights`` used to combine the score components."""

    pct_sold: RateStr
    margin: RateStr
    review: RateStr


class ScorecardRow(BaseModel):
    """One product's full rating line."""

    product_id: int
    name: str
    code: str
    category: str | None
    brand: str | None  # supplier name
    supplier_id: int | None
    shelf_life_days: int | None
    buying_price: MoneyStr
    sold_price: MoneyStr
    vat_rate: RateStr
    profit_margin: Money | None  # (sell_ex_vat - buy) / sell_ex_vat, fraction
    total_sold_qty: int
    total_added_qty: int
    pct_sold: Money | None  # sold / added, fraction
    positive_reviews: int
    negative_reviews: int
    pct_positive_review: Money | None  # positive / (positive + negative)
    final_score: Money


class ScorecardPage(BaseModel):
    """Paginated scorecard plus the weights and window it was computed over."""

    items: list[ScorecardRow]
    total: int
    limit: int
    offset: int
    window_days: int
    period_end: datetime.date
    weights: ScorecardWeights
