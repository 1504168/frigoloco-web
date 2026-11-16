"""Forecast engine - legacy parity implementation of R1.

Formula (IMPLEMENTATION-BRIEF §formulas):

    forecast = (cat_sold / (valid_days + no_info_days)) * days_to_fill * (1 + margin)

* The forecast method (``app.services.forecast.strategies``) picks the sales window;
  the formula is the same for every method. Fridges are those with a
  ``fridge_delivery_config`` row on the delivery weekday.
* A recent-sales window (last 3 weeks / 3 months) ends yesterday at the latest:
  for a delivery further ahead, days that have not happened yet would count as
  no-info days and shrink the average.
* A window day is a *holiday* (excluded from ``valid_days``) when the fridge's
  total units sold that day is ``<= min_daily_qty``.
* Days in the window with no sales rows at all are *no-info* days; they stay in
  the denominator so sparse history degrades the average gracefully (a zero
  denominator yields a zero forecast).
* A fridge with ``active_on_weekends = false`` sells only Monday to Friday:
  Saturdays and Sundays are dropped from the sales window (they are neither
  valid, holiday nor no-info days) and from the days the delivery must cover,
  so ``days_to_fill`` becomes the number of weekdays until the next delivery.
* Bank holidays (``bank_holidays`` table) are never selling days: they leave
  the sales window and the days to fill the same way weekends do.
* Current fridge stock still good through the coverage window is deducted only
  when the delivery is the next one for its weekday: ``fridge_stock`` holds the
  latest reading only, so it says nothing about stock on a later delivery date.
  The good-unit rule lives in :mod:`app.services.fridge_stock_service`.
* Reads local ``sales_events`` only - never the Husky live API.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, Numeric, column, delete, select, text, update, values
from sqlalchemy.orm import Session

from app.husky.sync import effective_status_clause
from app.models.master import Category, Fridge, FridgeDeliveryConfig, Product, Setting
from app.models.planning import ForecastResult, ForecastRun
from app.schemas.forecasts import ForecastCellEdit
from app.schemas.masters import api_error
from app.services import fridge_stock_service
from app.services.forecast.bank_holidays import load_bank_holiday_labels
from app.services.forecast.strategies import (
    DEFAULT_STRATEGY_CODE,
    SalesWindow,
    get_strategy,
)
from app.services.selling_days import count_selling_days, is_selling_day
from app.services.stock_service import day_name_for_date, record_audit

_LOCAL_TZ = "Europe/Brussels"
_TWO_PLACES = Decimal("0.01")
_RATIO_PLACES = Decimal("0.0001")
_MARGINS_SETTING_KEY = "forecast_margins"
# A delivery within this many days of today is the next one on its weekday.
_NEXT_DELIVERY_HORIZON_DAYS = 7
_PRODUCT_STATUS_ACTIVE = "active"
_SAVED_RUNS_LIMIT = 200


@dataclass(frozen=True)
class ForecastCell:
    fridge_id: int
    category_id: int
    # Net quantity to deliver: gross_qty minus residual_units, never below zero.
    forecast_qty: Decimal
    gross_qty: Decimal
    # Good in-fridge stock units deducted (0 when the residual rule did not apply).
    residual_units: int
    valid_days: int
    holiday_days: int
    no_info_days: int


@dataclass(frozen=True)
class RunSummary:
    """What the forecast page shows next to a run's grid."""

    window: SalesWindow
    window_sales_units: int
    sold_units_by_fridge: dict[int, int]
    hidden_category_ids: list[int]
    residual_applied: bool
    # Label when the delivery date itself is a bank holiday.
    delivery_bank_holiday: str | None


@dataclass(frozen=True)
class ActualCell:
    """Raw added/sold totals (and their ratio) for one fridge x category."""

    fridge_id: int
    category_id: int
    added_qty: int
    sold_qty: int
    ratio: Decimal | None


@dataclass(frozen=True)
class ActualsReport:
    window: SalesWindow
    cells: list[ActualCell]


@dataclass(frozen=True)
class _FridgeConfig:
    fridge_id: int
    min_daily_qty: int
    days_to_fill: int
    active_on_weekends: bool


@dataclass(frozen=True)
class _SellingCalendar:
    """What makes a day a selling day for one fridge."""

    active_on_weekends: bool
    bank_holidays: frozenset[datetime.date]


@dataclass(frozen=True)
class _RunComputation:
    """Pure result of computing a forecast (no DB writes yet)."""

    params: dict
    cells: list[ForecastCell]


def run_forecast(
    *,
    delivery_date: datetime.date,
    fridge_ids: list[int] | None,
    model: str = DEFAULT_STRATEGY_CODE,
    extra_params: dict | None = None,
    user_id: int | None,
    session: Session,
) -> ForecastRun:
    """Compute a forecast and persist it as an UNSAVED run.

    The row persists so the page and the allocator have a ``run_id``; promote it
    to the one saved forecast for its delivery date via :func:`save_forecast`.
    Earlier unsaved runs for the same delivery date and method are replaced.
    """
    computation = _compute_run(
        delivery_date=delivery_date,
        fridge_ids=fridge_ids,
        model=model,
        extra_params=extra_params,
        session=session,
    )
    _delete_unsaved_runs(delivery_date, model, session)

    run = ForecastRun(
        delivery_date=delivery_date,
        model=model,
        day_name=day_name_for_date(delivery_date),
        params=computation.params,
        created_by=user_id,
    )
    session.add(run)
    session.flush()
    _insert_results(run.id, computation.cells, session)

    record_audit(
        session,
        action="forecast.run",
        entity="forecast_runs",
        entity_id=run.id,
        after={
            "delivery_date": delivery_date.isoformat(),
            "model": model,
            "is_saved": False,
        },
        user_id=user_id,
    )
    session.commit()
    session.refresh(run)
    return run


def save_forecast(
    *,
    run_id: int,
    cells: Sequence[ForecastCellEdit],
    overwrite: bool,
    user_id: int | None,
    session: Session,
) -> ForecastRun:
    """Save run ``run_id`` with the quantities shown on screen as THE saved forecast.

    A saved forecast already existing for the delivery date (including this run
    itself, when it was loaded and edited) yields ``409 {code:"exists"}`` unless
    ``overwrite`` is set. Overwriting another run deletes it (results cascade).
    """
    run = session.get(ForecastRun, run_id)
    if run is None:
        raise api_error(
            404,
            "not_found",
            "Forecast run not found; run the forecast again",
            {"run_id": run_id},
        )
    saved_run = get_saved_run(run.delivery_date, session)
    if saved_run is not None and not overwrite:
        raise api_error(
            409,
            "exists",
            "A saved forecast already exists for this key; resend with overwrite=true",
            {"delivery_date": run.delivery_date.isoformat(), "run_id": saved_run.id},
        )

    _apply_screen_quantities(run.id, cells, session)
    replaced_run_id = None
    if saved_run is not None and saved_run.id != run.id:
        replaced_run_id = saved_run.id
        session.delete(saved_run)
        # The old saved row must be gone before this run takes the unique saved slot.
        session.flush()

    run.is_saved = True
    run.day_name = day_name_for_date(run.delivery_date)
    record_audit(
        session,
        action="forecast.save.overwrite" if saved_run is not None else "forecast.save",
        entity="forecast_runs",
        entity_id=run.id,
        before={"run_id": replaced_run_id} if replaced_run_id is not None else None,
        after={
            "delivery_date": run.delivery_date.isoformat(),
            "model": run.model,
            "day_name": run.day_name,
            "is_saved": True,
            "cells": len(cells),
        },
        user_id=user_id,
    )
    session.commit()
    session.refresh(run)
    return run


def summarize_run(
    run: ForecastRun,
    results: list[ForecastResult],
    session: Session,
) -> RunSummary:
    """Sales window, its sales volume and the categories worth hiding for a run."""
    window = _run_window(run)
    fridge_ids = sorted({result.fridge_id for result in results})
    category_ids = sorted({result.category_id for result in results})
    sold_by_key = _sold_units_by_fridge_category(fridge_ids, window, session)
    sold_by_category: dict[int, int] = {}
    sold_by_fridge: dict[int, int] = {}
    for (fridge_id, category_id), units in sold_by_key.items():
        sold_by_category[category_id] = sold_by_category.get(category_id, 0) + units
        sold_by_fridge[fridge_id] = sold_by_fridge.get(fridge_id, 0) + units
    active_category_ids = _categories_with_active_products(session)
    delivery_holiday_labels = load_bank_holiday_labels(
        run.delivery_date,
        run.delivery_date,
        session,
    )

    hidden_category_ids = []
    for category_id in category_ids:
        has_sales = sold_by_category.get(category_id, 0) > 0
        if not has_sales and category_id not in active_category_ids:
            hidden_category_ids.append(category_id)

    return RunSummary(
        window=window,
        window_sales_units=sum(sold_by_category.values()),
        sold_units_by_fridge=sold_by_fridge,
        hidden_category_ids=hidden_category_ids,
        # Runs created before the residual feature carry no flag: nothing was deducted.
        residual_applied=bool(run.params.get("residual_deduction", False)),
        delivery_bank_holiday=delivery_holiday_labels.get(run.delivery_date),
    )


def get_saved_run(delivery_date: datetime.date, session: Session) -> ForecastRun | None:
    """Load the saved forecast for a delivery date (import-from-database, D2)."""
    return session.execute(
        select(ForecastRun).where(
            ForecastRun.delivery_date == delivery_date,
            ForecastRun.is_saved.is_(True),
        )
    ).scalar_one_or_none()


def list_saved_runs(year: int | None, session: Session) -> list[ForecastRun]:
    """Saved forecasts (of delivery ``year`` when given), latest delivery date first."""
    stmt = (
        select(ForecastRun)
        .where(ForecastRun.is_saved.is_(True))
        .order_by(ForecastRun.delivery_date.desc())
        .limit(_SAVED_RUNS_LIMIT)
    )
    if year is not None:
        stmt = stmt.where(
            ForecastRun.delivery_date >= datetime.date(year, 1, 1),
            ForecastRun.delivery_date <= datetime.date(year, 12, 31),
        )
    return list(session.execute(stmt).scalars().all())


def get_run(run_id: int, session: Session) -> ForecastRun | None:
    return session.get(ForecastRun, run_id)


def get_results(run_id: int, session: Session) -> list[ForecastResult]:
    return list(
        session.execute(
            select(ForecastResult)
            .where(ForecastResult.run_id == run_id)
            .order_by(ForecastResult.fridge_id, ForecastResult.category_id)
        )
        .scalars()
        .all()
    )


def get_actuals(
    *,
    delivery_date: datetime.date,
    model: str,
    fridge_ids: list[int] | None,
    compare_window: SalesWindow | None = None,
    weekdays: list[int] | None = None,
    session: Session,
) -> ActualsReport:
    """Actual added vs sold per fridge x category over the method's sales window.

    Same window and delivery-weekday fridge set the forecast run uses, unless
    ``compare_window`` replaces the window; ``weekdays`` (ISO 1-7) keeps only
    those days of it. ``added_qty`` counts VALID ADDED ``restock_events``;
    ``sold_qty`` counts non-refunded ``sales_events``. ``ratio`` = sold/added
    (None when nothing was added). Returns only cells with any activity; the
    caller treats missing keys as 0/0. No fridge configured for the weekday
    gives no cells.
    """
    window = compare_window or _sales_window(model, delivery_date)
    configs = _target_configs(delivery_date.isoweekday(), fridge_ids, session)
    target_fridge_ids = [config.fridge_id for config in configs]

    added = _event_count_by_fridge_category(
        table="restock_events",
        timestamp_col="occurred_at",
        fridge_ids=target_fridge_ids,
        window=window,
        weekdays=weekdays,
        extra_where="e.action = 'added' AND e.tag_status = 'valid'",
        session=session,
    )
    sold = _event_count_by_fridge_category(
        table="sales_events",
        timestamp_col="sold_at",
        fridge_ids=target_fridge_ids,
        window=window,
        weekdays=weekdays,
        extra_where="e.is_refunded = false",
        session=session,
    )

    active_keys = sorted(set(added) | set(sold))
    cells: list[ActualCell] = []
    for fridge_id, category_id in active_keys:
        added_qty = added.get((fridge_id, category_id), 0)
        sold_qty = sold.get((fridge_id, category_id), 0)
        ratio = None
        if added_qty > 0:
            ratio = (Decimal(sold_qty) / Decimal(added_qty)).quantize(_RATIO_PLACES)
        cells.append(
            ActualCell(
                fridge_id=fridge_id,
                category_id=category_id,
                added_qty=added_qty,
                sold_qty=sold_qty,
                ratio=ratio,
            )
        )
    return ActualsReport(window=window, cells=cells)


def get_latest_run(
    delivery_date: datetime.date | None, session: Session
) -> ForecastRun | None:
    stmt = select(ForecastRun)
    if delivery_date is not None:
        stmt = stmt.where(ForecastRun.delivery_date == delivery_date)
    stmt = stmt.order_by(ForecastRun.run_at.desc(), ForecastRun.id.desc()).limit(1)
    return session.execute(stmt).scalars().first()


def _sales_window(model: str, delivery_date: datetime.date) -> SalesWindow:
    return get_strategy(model).sales_window(delivery_date, sales_until=_local_today())


def _run_window(run: ForecastRun) -> SalesWindow:
    """The window the run was computed on; it moves with today, so recomputing could differ."""
    # Runs imported from the Excel history carry no window in their params.
    if "window_start" not in run.params:
        return _sales_window(run.model, run.delivery_date)
    return SalesWindow(
        start=datetime.date.fromisoformat(run.params["window_start"]),
        end=datetime.date.fromisoformat(run.params["window_end"]),
    )


def _compute_run(
    *,
    delivery_date: datetime.date,
    fridge_ids: list[int] | None,
    model: str,
    extra_params: dict | None,
    session: Session,
) -> _RunComputation:
    """Compute forecast cells for ``delivery_date`` without writing anything."""
    window = _sales_window(model, delivery_date)
    delivery_weekday = delivery_date.isoweekday()
    configs = _target_configs(delivery_weekday, fridge_ids, session)
    if not configs:
        raise api_error(
            409,
            "no_delivery_config",
            "No fridge has a delivery configuration for this weekday",
            {"delivery_date": delivery_date.isoformat(), "weekday": delivery_weekday},
        )

    category_ids = list(session.execute(select(Category.id)).scalars().all())
    stored_margins = _load_margins(session)
    margins_by_id = {
        category_id: stored_margins.get(category_id, Decimal("0"))
        for category_id in category_ids
    }

    target_fridge_ids = [config.fridge_id for config in configs]
    per_fridge_units = _daily_category_units(target_fridge_ids, window, session)
    residual_applied = is_next_delivery(delivery_date)
    bank_holidays = _bank_holidays_for_run(window, delivery_date, configs, session)
    residual: dict[tuple[int, int], int] = {}
    if residual_applied:
        residual = _residual_by_key(configs, delivery_date, bank_holidays, session)
    selling_days_to_fill_by_fridge = {
        config.fridge_id: count_selling_days(
            delivery_date,
            config.days_to_fill,
            config.active_on_weekends,
            bank_holidays,
        )
        for config in configs
    }

    params: dict = {
        "model": model,
        "window_start": window.start.isoformat(),
        "window_end": window.end.isoformat(),
        "window_days": window.days,
        "delivery_weekday": delivery_weekday,
        "triggered_by": "manual",
        "residual_deduction": residual_applied,
        "excluded_bank_holidays": [holiday.isoformat() for holiday in sorted(bank_holidays)],
        "margins": {str(cid): str(margin) for cid, margin in margins_by_id.items()},
        "fridge_config": {
            str(config.fridge_id): {
                "min_daily_qty": config.min_daily_qty,
                "days_to_fill": config.days_to_fill,
                "selling_days_to_fill": selling_days_to_fill_by_fridge[config.fridge_id],
                "active_on_weekends": config.active_on_weekends,
            }
            for config in configs
        },
    }
    if extra_params:
        params.update(extra_params)

    cells: list[ForecastCell] = []
    for config in configs:
        residual_by_category = {
            category_id: units
            for (fridge_id, category_id), units in residual.items()
            if fridge_id == config.fridge_id
        }
        cells.extend(
            _compute_cells(
                config=config,
                day_cat_units=per_fridge_units.get(config.fridge_id, {}),
                window=window,
                selling_calendar=_SellingCalendar(
                    active_on_weekends=config.active_on_weekends,
                    bank_holidays=bank_holidays,
                ),
                selling_days_to_fill=selling_days_to_fill_by_fridge[config.fridge_id],
                category_ids=category_ids,
                margins_by_id=margins_by_id,
                residual_by_category=residual_by_category,
            )
        )
    return _RunComputation(params=params, cells=cells)


def _compute_cells(
    *,
    config: _FridgeConfig,
    day_cat_units: dict[tuple[datetime.date, int], int],
    window: SalesWindow,
    selling_calendar: _SellingCalendar,
    selling_days_to_fill: int,
    category_ids: list[int],
    margins_by_id: dict[int, Decimal],
    residual_by_category: dict[int, int],
) -> list[ForecastCell]:
    day_totals: dict[datetime.date, int] = {}
    for (day, _category_id), units in day_cat_units.items():
        if is_selling_day(
            day,
            selling_calendar.active_on_weekends,
            selling_calendar.bank_holidays,
        ):
            day_totals[day] = day_totals.get(day, 0) + units

    valid_days = {
        day for day, total in day_totals.items() if total > config.min_daily_qty
    }
    holiday_count = len(day_totals) - len(valid_days)
    window_selling_days = count_selling_days(
        window.start,
        window.days,
        selling_calendar.active_on_weekends,
        selling_calendar.bank_holidays,
    )
    no_info_days = window_selling_days - len(day_totals)
    denominator = len(valid_days) + no_info_days

    cells: list[ForecastCell] = []
    for category_id in category_ids:
        cat_sold = sum(
            units
            for (day, cid), units in day_cat_units.items()
            if cid == category_id and day in valid_days
        )
        if denominator > 0:
            margin = margins_by_id[category_id]
            raw = (
                (Decimal(cat_sold) / Decimal(denominator))
                * Decimal(selling_days_to_fill)
                * (Decimal("1") + margin)
            )
            gross_qty = raw.quantize(_TWO_PLACES)
        else:
            gross_qty = Decimal("0.00")
        # Residual-stock deduction (slide 5): deliver only the net need, never below zero.
        residual_units = residual_by_category.get(category_id, 0)
        net_qty = max(Decimal("0.00"), gross_qty - Decimal(residual_units))
        cells.append(
            ForecastCell(
                fridge_id=config.fridge_id,
                category_id=category_id,
                forecast_qty=net_qty,
                gross_qty=gross_qty,
                residual_units=residual_units,
                valid_days=len(valid_days),
                holiday_days=holiday_count,
                no_info_days=no_info_days,
            )
        )
    return cells


def _bank_holidays_for_run(
    window: SalesWindow,
    delivery_date: datetime.date,
    configs: list[_FridgeConfig],
    session: Session,
) -> frozenset[datetime.date]:
    """Bank holidays inside the sales window or inside any fridge's days to fill."""
    longest_days_to_fill = max(config.days_to_fill for config in configs)
    last_day_to_fill = delivery_date + datetime.timedelta(days=longest_days_to_fill - 1)
    holiday_labels = load_bank_holiday_labels(window.start, last_day_to_fill, session)
    # Last-year windows leave a gap of a year before the delivery date: skip its holidays.
    relevant_holidays = [
        holiday
        for holiday in holiday_labels
        if window.start <= holiday < window.end or holiday >= delivery_date
    ]
    return frozenset(relevant_holidays)


def _load_margins(session: Session) -> dict[int, Decimal]:
    """Per-category margin fractions keyed by category id (migration 0015)."""
    setting = session.get(Setting, _MARGINS_SETTING_KEY)
    if setting is None:
        return {}
    return {
        int(category_id): Decimal(str(margin))
        for category_id, margin in setting.value.items()
    }


def _target_configs(
    delivery_weekday: int, fridge_ids: list[int] | None, session: Session
) -> list[_FridgeConfig]:
    stmt = (
        select(FridgeDeliveryConfig, Fridge.active_on_weekends)
        .join(Fridge, Fridge.id == FridgeDeliveryConfig.fridge_id)
        .where(FridgeDeliveryConfig.weekday == delivery_weekday)
    )
    if fridge_ids is not None:
        stmt = stmt.where(FridgeDeliveryConfig.fridge_id.in_(fridge_ids))
    return [
        _FridgeConfig(
            fridge_id=row.FridgeDeliveryConfig.fridge_id,
            min_daily_qty=row.FridgeDeliveryConfig.min_daily_qty,
            days_to_fill=row.FridgeDeliveryConfig.days_to_fill,
            active_on_weekends=row.active_on_weekends,
        )
        for row in session.execute(stmt).all()
    ]


def _daily_category_units(
    fridge_ids: list[int],
    window: SalesWindow,
    session: Session,
) -> dict[int, dict[tuple[datetime.date, int], int]]:
    """Return per-fridge {(day, category_id): units} over the sales window."""
    if not fridge_ids:
        return {}
    rows = session.execute(
        text(
            "SELECT se.fridge_id AS fridge_id, "
            f"(se.sold_at AT TIME ZONE '{_LOCAL_TZ}')::date AS day, "
            "p.category_id AS category_id, count(*) AS units "
            "FROM sales_events se JOIN products p ON p.id = se.product_id "
            "WHERE se.fridge_id = ANY(:fridge_ids) AND se.is_refunded = false "
            f"AND (se.sold_at AT TIME ZONE '{_LOCAL_TZ}')::date >= :start "
            f"AND (se.sold_at AT TIME ZONE '{_LOCAL_TZ}')::date < :end "
            "GROUP BY se.fridge_id, day, p.category_id"
        ),
        {"fridge_ids": fridge_ids, "start": window.start, "end": window.end},
    ).all()

    per_fridge: dict[int, dict[tuple[datetime.date, int], int]] = {}
    for row in rows:
        fridge_units = per_fridge.setdefault(row.fridge_id, {})
        fridge_units[(row.day, row.category_id)] = int(row.units)
    return per_fridge


def is_next_delivery(delivery_date: datetime.date) -> bool:
    """True when ``delivery_date`` is today or the next delivery on its weekday."""
    today = _local_today()
    horizon_end = today + datetime.timedelta(days=_NEXT_DELIVERY_HORIZON_DAYS)
    return today <= delivery_date < horizon_end


def _local_today() -> datetime.date:
    return datetime.datetime.now(ZoneInfo(_LOCAL_TZ)).date()


def _residual_by_key(
    configs: list[_FridgeConfig],
    delivery_date: datetime.date,
    bank_holidays: frozenset[datetime.date],
    session: Session,
) -> dict[tuple[int, int], int]:
    """Deductible in-fridge units per (fridge, category): stock good until the coverage end."""
    coverage_end_by_fridge = {
        config.fridge_id: fridge_stock_service.coverage_end(
            delivery_date,
            config.days_to_fill,
            config.active_on_weekends,
            bank_holidays,
        )
        for config in configs
    }
    good_stock = fridge_stock_service.load_good_stock_units(
        coverage_end_by_fridge=coverage_end_by_fridge,
        session=session,
    )
    residual: dict[tuple[int, int], int] = {}
    for product_stock in good_stock:
        key = (product_stock.fridge_id, product_stock.category_id)
        residual[key] = residual.get(key, 0) + product_stock.good_units
    return residual


def _delete_unsaved_runs(delivery_date: datetime.date, model: str, session: Session) -> None:
    session.execute(
        delete(ForecastRun).where(
            ForecastRun.delivery_date == delivery_date,
            ForecastRun.model == model,
            ForecastRun.is_saved.is_(False),
        )
    )


def _insert_results(run_id: int, cells: list[ForecastCell], session: Session) -> None:
    for cell in cells:
        session.add(
            ForecastResult(
                run_id=run_id,
                fridge_id=cell.fridge_id,
                category_id=cell.category_id,
                forecast_qty=cell.forecast_qty,
                gross_qty=cell.gross_qty,
                residual_units=cell.residual_units,
                valid_days=cell.valid_days,
                holiday_days=cell.holiday_days,
            )
        )


def _apply_screen_quantities(
    run_id: int,
    cells: Sequence[ForecastCellEdit],
    session: Session,
) -> None:
    """Overwrite the run's quantities with the values the user saw (and edited)."""
    run_keys = set(
        session.execute(
            select(ForecastResult.fridge_id, ForecastResult.category_id).where(
                ForecastResult.run_id == run_id
            )
        )
        .tuples()
        .all()
    )
    unknown_keys = [
        {"fridge_id": cell.fridge_id, "category_id": cell.category_id}
        for cell in cells
        if (cell.fridge_id, cell.category_id) not in run_keys
    ]
    if unknown_keys:
        raise api_error(
            422,
            "validation_error",
            "Some cells do not belong to this forecast run",
            {"run_id": run_id, "cells": unknown_keys},
        )
    # Keyed so a cell sent twice keeps its last value, as one UPDATE row per key requires.
    screen_qty_by_key = {
        (cell.fridge_id, cell.category_id): cell.forecast_qty.quantize(
            _TWO_PLACES, rounding=ROUND_HALF_UP
        )
        for cell in cells
    }
    if not screen_qty_by_key:
        return
    _bulk_update_quantities(run_id, screen_qty_by_key, session)


def _bulk_update_quantities(
    run_id: int,
    qty_by_key: dict[tuple[int, int], Decimal],
    session: Session,
) -> None:
    """One UPDATE ... FROM (VALUES ...) round trip instead of one UPDATE per cell."""
    screen_rows = [
        (fridge_id, category_id, forecast_qty)
        for (fridge_id, category_id), forecast_qty in qty_by_key.items()
    ]
    screen = values(
        column("fridge_id", Integer),
        column("category_id", Integer),
        column("forecast_qty", Numeric(10, 2)),
        name="screen",
    ).data(screen_rows)
    session.execute(
        update(ForecastResult)
        .where(
            ForecastResult.run_id == run_id,
            ForecastResult.fridge_id == screen.c.fridge_id,
            ForecastResult.category_id == screen.c.category_id,
        )
        .values(forecast_qty=screen.c.forecast_qty)
        .execution_options(synchronize_session="fetch")
    )


def _sold_units_by_fridge_category(
    fridge_ids: list[int],
    window: SalesWindow,
    session: Session,
) -> dict[tuple[int, int], int]:
    return _event_count_by_fridge_category(
        table="sales_events",
        timestamp_col="sold_at",
        fridge_ids=fridge_ids,
        window=window,
        weekdays=None,
        extra_where="e.is_refunded = false",
        session=session,
    )


def _categories_with_active_products(session: Session) -> set[int]:
    active_clause = effective_status_clause(Product, _PRODUCT_STATUS_ACTIVE)
    category_ids = session.execute(
        select(Product.category_id).where(active_clause).distinct()
    ).scalars()
    return set(category_ids)


def _event_count_by_fridge_category(
    *,
    table: str,
    timestamp_col: str,
    fridge_ids: list[int],
    window: SalesWindow,
    weekdays: list[int] | None,
    extra_where: str,
    session: Session,
) -> dict[tuple[int, int], int]:
    """Event counts per (fridge_id, category_id) over the local-day sales window.

    ``weekdays`` (ISO 1-7) keeps only those days of the window; None keeps every day.
    """
    if not fridge_ids:
        return {}
    local_day = f"(e.{timestamp_col} AT TIME ZONE '{_LOCAL_TZ}')::date"
    weekday_filter = f"AND EXTRACT(ISODOW FROM {local_day}) = ANY(:weekdays) " if weekdays else ""
    rows = session.execute(
        text(
            f"SELECT e.fridge_id AS fridge_id, p.category_id AS category_id, "
            f"count(*) AS qty FROM {table} e "
            "JOIN products p ON p.id = e.product_id "
            "WHERE e.fridge_id = ANY(:fridge_ids) "
            f"AND {extra_where} "
            f"AND {local_day} >= :start "
            f"AND {local_day} < :end "
            f"{weekday_filter}"
            "GROUP BY e.fridge_id, p.category_id"
        ),
        {
            "fridge_ids": fridge_ids,
            "start": window.start,
            "end": window.end,
            "weekdays": weekdays,
        },
    ).all()
    return {(row.fridge_id, row.category_id): int(row.qty) for row in rows}
