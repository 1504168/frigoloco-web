"""Forecast runs (R1) and product scores (R2)."""

from __future__ import annotations

import datetime

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.forecasts import (
    ForecastActualCell,
    ForecastActualsOut,
    ForecastResultOut,
    ForecastRunOut,
    ForecastRunRequest,
    ForecastSaveRequest,
    ProductScoreOut,
    ScoreRecomputeRequest,
    ScoreRecomputeResult,
)
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.services import forecast_service, scoring_service
from app.services.stock_service import day_name_for_date, resolve_delivery_date

router = make_router(prefix="/api/v1/forecasts", tags=["forecasts"])


def _run_to_out(run, session: Session) -> ForecastRunOut:
    results = forecast_service.get_results(run.id, session)
    meta = forecast_service.get_run_meta(run.id, session)
    iso_year, week_no, _weekday = run.delivery_date.isocalendar()
    return ForecastRunOut(
        run_id=run.id,
        delivery_date=run.delivery_date,
        iso_year=iso_year,
        week_no=week_no,
        day_name=meta.day_name or day_name_for_date(run.delivery_date),
        run_at=run.run_at,
        model=meta.model,
        is_saved=meta.is_saved,
        params=run.params,
        results=[ForecastResultOut.model_validate(row) for row in results],
    )


@router.post("/run", response_model=ForecastRunOut)
def run_forecast(
    body: ForecastRunRequest, session: Session = Depends(get_db)
) -> ForecastRunOut:
    run = forecast_service.run_forecast(
        delivery_date=body.delivery_date,
        fridge_ids=body.fridge_ids,
        model=body.model,
        extra_params=body.params,
        user_id=None,
        session=session,
    )
    return _run_to_out(run, session)


@router.post("/save", response_model=ForecastRunOut)
def save_forecast(
    body: ForecastSaveRequest, session: Session = Depends(get_db)
) -> ForecastRunOut:
    delivery_date = resolve_delivery_date(body.year, body.week, body.day_name)
    run = forecast_service.save_forecast(
        delivery_date=delivery_date,
        fridge_ids=body.fridge_ids,
        model=body.model,
        extra_params=body.params,
        overwrite=body.overwrite,
        user_id=None,
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
    session: Session = Depends(get_db),
) -> ForecastActualsOut:
    """Added/Sold/% actuals over the same 3-week window the forecast run uses."""
    delivery_date = resolve_delivery_date(year, week, day_name)
    window_start = delivery_date - datetime.timedelta(days=21)
    cells = forecast_service.get_actuals(
        delivery_date=delivery_date, fridge_ids=None, session=session
    )
    return ForecastActualsOut(
        year=year,
        week=week,
        day_name=day_name_for_date(delivery_date),
        delivery_date=delivery_date,
        window_start=window_start,
        window_end=delivery_date,
        cells=[ForecastActualCell.model_validate(cell) for cell in cells],
    )


@router.post("/scores/recompute", response_model=ScoreRecomputeResult)
def recompute_scores(
    body: ScoreRecomputeRequest, session: Session = Depends(get_db)
) -> ScoreRecomputeResult:
    as_of = body.as_of or datetime.date.today()
    scored = scoring_service.recompute_scores(
        as_of=as_of, user_id=None, session=session
    )
    return ScoreRecomputeResult(period_end=as_of, products_scored=scored)


@router.get("/scores", response_model=Page[ProductScoreOut])
def list_scores(
    page: PaginationParams = Depends(pagination),
    period_end: datetime.date | None = Query(default=None),
    product_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> Page[ProductScoreOut]:
    rows, total = scoring_service.list_scores(
        period_end=period_end,
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
