"""Product rating scorecard endpoint (D3): the stored scores of one window.

Lives under its own ``/api/v1/rating`` prefix (the forecasts router is owned by a
sibling agent). Uses the finance-half ``@envelope`` decorator so the ``ApiError``
raised for bad sort/window params renders as the standard error body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.masters import PaginationParams, pagination
from app.schemas.rating import ScorecardPage, ScorecardRow, ScorecardWeights
from app.services import finance_service
from app.services.finance_service import ScorecardFilters
from app.services.orders_service import envelope
from app.services.scoring_service import YEARLY_SCORE_WINDOW_DAYS, ScoreWindowDays

router = APIRouter(prefix="/api/v1/rating", tags=["rating"])


@router.get("/scorecard", response_model=ScorecardPage)
@envelope
def get_scorecard(
    page: PaginationParams = Depends(pagination),
    window_days: ScoreWindowDays = Query(default=YEARLY_SCORE_WINDOW_DAYS),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    search: str | None = Query(
        default=None, description="Case-insensitive 'contains' on product code or name"
    ),
    sort: str | None = Query(
        default=None, description="'<field> [asc|desc]', default 'final_score desc'"
    ),
    session: Session = Depends(get_db),
) -> ScorecardPage:
    filters = ScorecardFilters(
        category_id=category_id,
        supplier_id=supplier_id,
        search=search.strip() if search else None,
    )
    result = finance_service.build_scorecard(
        session,
        window_days=window_days,
        filters=filters,
        limit=page.limit,
        offset=page.offset,
        sort=sort,
    )
    return ScorecardPage(
        items=[ScorecardRow(**vars(row)) for row in result.rows],
        total=result.total,
        limit=page.limit,
        offset=page.offset,
        window_days=result.window_days,
        period_end=result.period_end,
        computed_at=result.computed_at,
        weights=ScorecardWeights(
            pct_sold=result.weights.pct_sold,
            margin=result.weights.margin,
            review=result.weights.review,
        ),
    )
