"""Schemas for the product rating scorecard (D3).

The scorecard shows the stored ``product_scores`` of one window with every
Excel-equivalent column per product, plus the scoring weights in the page
envelope, so the UI can render the rating grid and explain the final score.
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
    supplier_name: str | None
    shelf_life_days: int | None
    buying_price: MoneyStr
    sold_price: MoneyStr
    vat_rate: RateStr
    profit_margin: Money | None  # (sell_ex_vat - buy) / sell_ex_vat, fraction
    # Counts are None on rows stored before migration 0016 kept them.
    total_sold_qty: int | None
    total_added_qty: int
    pct_sold: Money | None  # sold / added, fraction
    positive_reviews: int | None
    negative_reviews: int | None
    pct_positive_review: Money | None  # positive / (positive + negative)
    final_score: Money
    uses_new_product_baseline: bool


class ScorecardPage(BaseModel):
    """Paginated stored scores plus the weights and window they were computed over.

    ``period_end`` and ``computed_at`` are None when the window was never computed.
    """

    items: list[ScorecardRow]
    total: int
    limit: int
    offset: int
    window_days: int
    period_end: datetime.date | None
    computed_at: datetime.datetime | None
    weights: ScorecardWeights
