"""Forecast runs (R1) and product scores (R2)."""

from __future__ import annotations

import datetime

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import User
from app.models.planning import ForecastRun
from app.schemas.forecasts import (
    ForecastActualCell,
    ForecastActualsOut,
    ForecastModelOut,
    ForecastResultOut,
    ForecastRunOut,
    ForecastRunRequest,
    ForecastSaveRequest,
    ProductScoreOut,
    ScoreRecomputeRequest,
    ScoreRecomputeResult,
)
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.security import get_current_user
from app.services import forecast_service, scoring_service
from app.services.forecast.strategies import DEFAULT_STRATEGY_CODE, FORECAST_STRATEGIES
from app.services.scoring_service import ScoreWindowDays
from app.services.stock_service import day_name_for_date, resolve_delivery_date

router = make_router(prefix="/api/v1/forecasts", tags=["forecasts"])


def _run_to_out(run: ForecastRun, session: Session) -> ForecastRunOut:
    results = forecast_service.get_results(run.id, session)
    summary = forecast_service.summarize_run(run, results, session)
    iso_year, week_no, _weekday = run.delivery_date.isocalendar()
    return ForecastRunOut(
        run_id=run.id,
        delivery_date=run.delivery_date,
        iso_year=iso_year,
        week_no=week_no,
        day_name=day_name_for_date(run.delivery_date),
        run_at=run.run_at,
        model=run.model,
        is_saved=run.is_saved,
        params=run.params,
        results=[ForecastResultOut.model_validate(row) for row in results],
        window_start=summary.window.start,
        window_end=summary.window.end,
        window_sales_units=summary.window_sales_units,
        hidden_category_ids=summary.hidden_category_ids,
        residual_applied=summary.residual_applied,
    )


@router.get("/models", response_model=list[ForecastModelOut])
def list_forecast_models() -> list[ForecastModelOut]:
    return [
        ForecastModelOut(code=strategy.code, label=strategy.label)
        for strategy in FORECAST_STRATEGIES.values()
    ]


@router.post("/run", response_model=ForecastRunOut)
def run_forecast(
    body: ForecastRunRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ForecastRunOut:
    run = forecast_service.run_forecast(
        delivery_date=body.delivery_date,
        fridge_ids=body.fridge_ids,
        model=body.model,
        extra_params=body.params,
        user_id=current_user.id,
        session=session,
    )
    return _run_to_out(run, session)


@router.post("/save", response_model=ForecastRunOut)
def save_forecast(
    body: ForecastSaveRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ForecastRunOut:
    run = forecast_service.save_forecast(
        run_id=body.run_id,
        cells=body.cells,
        overwrite=body.overwrite,
        user_id=current_user.id,
        session=session,
    )
    return _run_to_out(run, session)


@router.get("/saved", response_model=ForecastRunOut)
def load_saved_forecast(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    session: Session = Depends(get_db),
) -> ForecastRunOut:
    delivery_date = resolve_delivery_date(year, week, day_name)
    run = forecast_service.get_saved_run(delivery_date, session)
    if run is None:
        raise api_error(
            404,
            "not_found",
            "No saved forecast for this key",
            {"year": year, "week": week, "day_name": day_name},
        )
    return _run_to_out(run, session)


@router.get("/latest", response_model=ForecastRunOut)
def latest_forecast(
    delivery_date: datetime.date | None = Query(default=None),
    session: Session = Depends(get_db),
) -> ForecastRunOut:
    run = forecast_service.get_latest_run(delivery_date, session)
    if run is None:
        raise api_error(404, "not_found", "No forecast run found", None)
    return _run_to_out(run, session)


@router.get("/runs/{run_id}", response_model=ForecastRunOut)
def get_forecast_run(run_id: int, session: Session = Depends(get_db)) -> ForecastRunOut:
    run = forecast_service.get_run(run_id, session)
    if run is None:
        raise api_error(404, "not_found", "Forecast run not found", {"id": run_id})
    return _run_to_out(run, session)


@router.get("/actuals", response_model=ForecastActualsOut)
def forecast_actuals(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    model: str = Query(default=DEFAULT_STRATEGY_CODE),
    session: Session = Depends(get_db),
) -> ForecastActualsOut:
    """Added/Sold/% actuals over the same sales window the forecast method uses."""
    delivery_date = resolve_delivery_date(year, week, day_name)
    report = forecast_service.get_actuals(
        delivery_date=delivery_date,
        model=model,
        fridge_ids=None,
        session=session,
    )
    return ForecastActualsOut(
        year=year,
        week=week,
        day_name=day_name_for_date(delivery_date),
        delivery_date=delivery_date,
        window_start=report.window.start,
        window_end=report.window.end,
        cells=[ForecastActualCell.model_validate(cell) for cell in report.cells],
    )


@router.post("/scores/recompute", response_model=ScoreRecomputeResult)
def recompute_scores(
    body: ScoreRecomputeRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ScoreRecomputeResult:
    as_of = body.as_of or datetime.date.today()
    scored = scoring_service.recompute_scores(
        as_of=as_of,
        window_days=body.window_days,
        user_id=current_user.id,
        session=session,
    )
    return ScoreRecomputeResult(
        period_end=as_of,
        window_days=body.window_days,
        products_scored=scored,
    )


@router.get("/scores", response_model=Page[ProductScoreOut])
def list_scores(
    page: PaginationParams = Depends(pagination),
    period_end: datetime.date | None = Query(default=None),
    window_days: ScoreWindowDays = Query(default=scoring_service.YEARLY_SCORE_WINDOW_DAYS),
    product_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> Page[ProductScoreOut]:
    rows, total = scoring_service.list_scores(
        period_end=period_end,
        window_days=window_days,
        product_id=product_id,
        limit=page.limit,
        offset=page.offset,
        session=session,
    )
    return Page(
        items=[ProductScoreOut.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
