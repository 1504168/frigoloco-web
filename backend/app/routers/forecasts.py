"""Forecast runs (R1), bank holidays and product scores (R2)."""

from __future__ import annotations

import datetime

from fastapi import Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import User
from app.models.planning import ForecastRun
from app.schemas.forecasts import (
    BankHolidayIn,
    BankHolidayOut,
    ForecastActualCell,
    ForecastActualsOut,
    ForecastModelOut,
    ForecastResultOut,
    ForecastRunOut,
    ForecastRunRequest,
    ForecastSaveRequest,
    FridgeWindowSalesOut,
    ProductScoreOut,
    SavedForecastOut,
    ScoreRecomputeRequest,
    ScoreRecomputeResult,
)
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.security import get_current_user
from app.services import forecast_service, scoring_service
from app.services.forecast import bank_holidays
from app.services.forecast.strategies import (
    DEFAULT_STRATEGY_CODE,
    FORECAST_STRATEGIES,
    SalesWindow,
)
from app.services.scoring_service import ScoreWindowDays
from app.services.stock_service import day_name_for_date, resolve_delivery_date

router = make_router(prefix="/api/v1/forecasts", tags=["forecasts"])

# A compare window longer than this is a typo, not an analysis.
MAX_COMPARE_WINDOW_DAYS = 400
ISO_WEEKDAY_RANGE = range(1, 8)


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
        window_sales_by_fridge=[
            FridgeWindowSalesOut(fridge_id=fridge_id, sold_units=sold_units)
            for fridge_id, sold_units in summary.sold_units_by_fridge.items()
        ],
        hidden_category_ids=summary.hidden_category_ids,
        residual_applied=summary.residual_applied,
        delivery_bank_holiday=summary.delivery_bank_holiday,
    )


def _saved_run_to_out(run: ForecastRun) -> SavedForecastOut:
    iso_year, week_no, _weekday = run.delivery_date.isocalendar()
    return SavedForecastOut(
        run_id=run.id,
        delivery_date=run.delivery_date,
        iso_year=iso_year,
        week_no=week_no,
        day_name=day_name_for_date(run.delivery_date),
        model=run.model,
        run_at=run.run_at,
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


@router.get("/saved-list", response_model=list[SavedForecastOut])
def list_saved_forecasts(
    year: int | None = Query(default=None, ge=2020, le=2100),
    session: Session = Depends(get_db),
) -> list[SavedForecastOut]:
    """Saved forecasts, latest delivery date first."""
    runs = forecast_service.list_saved_runs(year, session)
    return [_saved_run_to_out(run) for run in runs]


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
    start: datetime.date | None = Query(default=None, description="Compare window first day"),
    end: datetime.date | None = Query(default=None, description="Compare window end, exclusive"),
    weekdays: str | None = Query(default=None, description="ISO weekdays, e.g. '1,2,3,4'"),
    session: Session = Depends(get_db),
) -> ForecastActualsOut:
    """Added/Sold/% actuals over the forecast method's sales window, or a compare window."""
    delivery_date = resolve_delivery_date(year, week, day_name)
    weekday_numbers = _parse_weekdays(weekdays)
    report = forecast_service.get_actuals(
        delivery_date=delivery_date,
        model=model,
        fridge_ids=None,
        compare_window=_compare_window(start, end),
        weekdays=weekday_numbers,
        session=session,
    )
    return ForecastActualsOut(
        year=year,
        week=week,
        day_name=day_name_for_date(delivery_date),
        delivery_date=delivery_date,
        window_start=report.window.start,
        window_end=report.window.end,
        weekdays=weekday_numbers,
        cells=[ForecastActualCell.model_validate(cell) for cell in report.cells],
    )


@router.get("/bank-holidays", response_model=list[BankHolidayOut])
def list_bank_holidays(
    year: int | None = Query(default=None, ge=2020, le=2100),
    session: Session = Depends(get_db),
) -> list[BankHolidayOut]:
    holidays = bank_holidays.list_bank_holidays(year, session)
    return [BankHolidayOut.model_validate(holiday) for holiday in holidays]


@router.post("/bank-holidays", response_model=BankHolidayOut, status_code=status.HTTP_201_CREATED)
def create_bank_holiday(
    body: BankHolidayIn,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BankHolidayOut:
    holiday = bank_holidays.create_bank_holiday(
        holiday_date=body.holiday_date,
        label=body.label,
        user_id=current_user.id,
        session=session,
    )
    return BankHolidayOut.model_validate(holiday)


@router.delete("/bank-holidays/{holiday_date}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_holiday(
    holiday_date: datetime.date,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    bank_holidays.delete_bank_holiday(
        holiday_date=holiday_date,
        user_id=current_user.id,
        session=session,
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


def _compare_window(
    start: datetime.date | None,
    end: datetime.date | None,
) -> SalesWindow | None:
    """The compare window from ``start``/``end``; None keeps the method's window."""
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise api_error(
            422,
            "validation_error",
            "Give both start and end for a compare window",
            None,
        )
    window = SalesWindow(start=start, end=end)
    if not 0 < window.days <= MAX_COMPARE_WINDOW_DAYS:
        raise api_error(
            422,
            "validation_error",
            f"The compare window must be 1 to {MAX_COMPARE_WINDOW_DAYS} days long",
            {"start": start.isoformat(), "end": end.isoformat()},
        )
    return window


def _parse_weekdays(weekdays: str | None) -> list[int] | None:
    """'1,2,3,4' -> [1, 2, 3, 4]; None or '' keeps every day."""
    if not weekdays:
        return None
    parts = [part.strip() for part in weekdays.split(",")]
    if not all(part.isascii() and part.isdigit() and int(part) in ISO_WEEKDAY_RANGE for part in parts):
        raise api_error(
            422,
            "validation_error",
            "weekdays must be ISO weekday numbers 1-7, comma separated",
            {"weekdays": weekdays},
        )
    return sorted({int(part) for part in parts})
