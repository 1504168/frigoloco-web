"""Forecast engine - legacy parity implementation of R1.

Formula (IMPLEMENTATION-BRIEF §formulas):

    forecast = (cat_sold / (valid_days + no_info_days)) * days_to_fill * (1 + margin)

* 3-week (21-day) lookback ending the day before the delivery date, anchored on
  the fridge's delivery weekday via its ``fridge_delivery_config`` row.
* A lookback day is a *holiday* (excluded from ``valid_days``) when the fridge's
  total units sold that day is ``<= min_daily_qty``.
* Days in the window with no sales rows at all are *no-info* days; they stay in
  the denominator so sparse history degrades the average gracefully (no
  divide-by-zero - a zero denominator yields a zero forecast).
* Reads local ``sales_events`` only - never the Husky live API.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.master import Category, FridgeDeliveryConfig, Setting
from app.models.planning import ForecastResult, ForecastRun
from app.schemas.masters import api_error
from app.services.stock_service import day_name_for_date, record_audit

_LOOKBACK_DAYS = 21
_LOCAL_TZ = "Europe/Brussels"
_TWO_PLACES = Decimal("0.01")

# Extensible forecast-model registry (enum-style string, text + CHECK in the DB).
# Only the legacy 3-week moving average exists today; future models add here and
# to the ``chk_forecast_runs_model`` CHECK (migration 0005).
DEFAULT_MODEL = "moving_average_3w"
ALLOWED_MODELS: frozenset[str] = frozenset({DEFAULT_MODEL})


@dataclass(frozen=True)
class ForecastCell:
    fridge_id: int
    category_id: int
    forecast_qty: Decimal
    valid_days: int
    holiday_days: int
    no_info_days: int


@dataclass(frozen=True)
class _FridgeConfig:
    fridge_id: int
    min_daily_qty: int
    days_to_fill: int


def _load_margins(session: Session) -> dict[str, Decimal]:
    setting = session.get(Setting, "forecast_margins")
    if setting is None or not isinstance(setting.value, dict):
        return {}
    return {name: Decimal(str(pct)) for name, pct in setting.value.items()}


def _target_configs(
    delivery_weekday: int, fridge_ids: list[int] | None, session: Session
) -> list[_FridgeConfig]:
    stmt = select(FridgeDeliveryConfig).where(
        FridgeDeliveryConfig.weekday == delivery_weekday
    )
    if fridge_ids is not None:
        stmt = stmt.where(FridgeDeliveryConfig.fridge_id.in_(fridge_ids))
    return [
        _FridgeConfig(
            fridge_id=row.fridge_id,
            min_daily_qty=row.min_daily_qty,
            days_to_fill=row.days_to_fill,
        )
        for row in session.execute(stmt).scalars().all()
    ]


def _daily_category_units(
    fridge_ids: list[int],
    window_start: datetime.date,
    delivery_date: datetime.date,
    session: Session,
) -> dict[int, dict[tuple[datetime.date, int], int]]:
    """Return per-fridge {(day, category_id): units} over the lookback window."""
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
        {"fridge_ids": fridge_ids, "start": window_start, "end": delivery_date},
    ).all()

    per_fridge: dict[int, dict[tuple[datetime.date, int], int]] = {}
    for row in rows:
        per_fridge.setdefault(row.fridge_id, {})[(row.day, row.category_id)] = int(
            row.units
        )
    return per_fridge


def _compute_cells(
    config: _FridgeConfig,
    day_cat_units: dict[tuple[datetime.date, int], int],
    category_ids: list[int],
    margins_by_id: dict[int, Decimal],
) -> list[ForecastCell]:
    day_totals: dict[datetime.date, int] = {}
    for (day, _category_id), units in day_cat_units.items():
        day_totals[day] = day_totals.get(day, 0) + units

    valid_days = {
        day for day, total in day_totals.items() if total > config.min_daily_qty
    }
    holiday_count = len(day_totals) - len(valid_days)
    no_info_days = _LOOKBACK_DAYS - len(day_totals)
    denominator = len(valid_days) + no_info_days

    cells: list[ForecastCell] = []
    for category_id in category_ids:
        cat_sold = sum(
            units
            for (day, cid), units in day_cat_units.items()
            if cid == category_id and day in valid_days
        )
        if denominator > 0:
            margin = margins_by_id.get(category_id, Decimal("0"))
            raw = (
                (Decimal(cat_sold) / Decimal(denominator))
                * Decimal(config.days_to_fill)
                * (Decimal("1") + margin)
            )
            forecast_qty = raw.quantize(_TWO_PLACES)
        else:
            forecast_qty = Decimal("0.00")
        cells.append(
            ForecastCell(
                fridge_id=config.fridge_id,
                category_id=category_id,
                forecast_qty=forecast_qty,
                valid_days=len(valid_days),
                holiday_days=holiday_count,
                no_info_days=no_info_days,
            )
        )
    return cells


@dataclass(frozen=True)
class _RunComputation:
    """Pure result of computing a forecast (no DB writes yet)."""

    params: dict
    cells: list[ForecastCell]


def _validate_model(model: str) -> str:
    if model not in ALLOWED_MODELS:
        raise api_error(
            422,
            "validation_error",
            "Unknown forecast model",
            {"model": model, "allowed": sorted(ALLOWED_MODELS)},
        )
    return model


def _compute_run(
    *,
    delivery_date: datetime.date,
    fridge_ids: list[int] | None,
    model: str,
    extra_params: dict | None,
    session: Session,
) -> _RunComputation:
    """Compute forecast cells for ``delivery_date`` - never touches the DB writes.

    Shared by :func:`run_forecast` (ephemeral preview) and :func:`save_forecast`
    (persisted keyed run) so the maths lives in exactly one place.
    """
    delivery_weekday = delivery_date.isoweekday()
    window_start = delivery_date - datetime.timedelta(days=_LOOKBACK_DAYS)

    configs = _target_configs(delivery_weekday, fridge_ids, session)
    if not configs:
        raise api_error(
            409,
            "no_delivery_config",
            "No fridge has a delivery configuration for this weekday",
            {"delivery_date": delivery_date.isoformat(), "weekday": delivery_weekday},
        )

    categories = list(session.execute(select(Category)).scalars().all())
    category_ids = [category.id for category in categories]
    margins_by_name = _load_margins(session)
    margins_by_id = {
        category.id: margins_by_name.get(category.name, Decimal("0"))
        for category in categories
    }

    target_fridge_ids = [config.fridge_id for config in configs]
    per_fridge_units = _daily_category_units(
        target_fridge_ids, window_start, delivery_date, session
    )

    params: dict = {
        "model": model,
        "window_days": _LOOKBACK_DAYS,
        "window_weeks": 3,
        "delivery_weekday": delivery_weekday,
        "triggered_by": "manual",
        "margins": {str(cid): str(margin) for cid, margin in margins_by_id.items()},
        "fridge_config": {
            str(config.fridge_id): {
                "min_daily_qty": config.min_daily_qty,
                "days_to_fill": config.days_to_fill,
            }
            for config in configs
        },
    }
    if extra_params:
        params.update(extra_params)

    cells: list[ForecastCell] = []
    for config in configs:
        cells.extend(
            _compute_cells(
                config,
                per_fridge_units.get(config.fridge_id, {}),
                category_ids,
                margins_by_id,
            )
        )
    return _RunComputation(params=params, cells=cells)


def _insert_results(run_id: int, cells: list[ForecastCell], session: Session) -> None:
    for cell in cells:
        session.add(
            ForecastResult(
                run_id=run_id,
                fridge_id=cell.fridge_id,
                category_id=cell.category_id,
                forecast_qty=cell.forecast_qty,
                valid_days=cell.valid_days,
                holiday_days=cell.holiday_days,
            )
        )


def run_forecast(
    *,
    delivery_date: datetime.date,
    fridge_ids: list[int] | None,
    model: str = DEFAULT_MODEL,
    extra_params: dict | None = None,
    user_id: int | None,
    session: Session,
) -> ForecastRun:
    """Compute a forecast and persist it as an EPHEMERAL (unsaved) run.

    D2: ``POST /forecasts/run`` computes and does NOT create the *saved* artifact
    (``is_saved`` stays false, the DB default). The row still persists so the
    preview has a ``run_id`` the allocator and ``/latest`` can reference; promote
    it to the one saved forecast for the key via :func:`save_forecast`.
    """
    _validate_model(model)
    computation = _compute_run(
        delivery_date=delivery_date,
        fridge_ids=fridge_ids,
        model=model,
        extra_params=extra_params,
        session=session,
    )

    run = ForecastRun(
        delivery_date=delivery_date, params=computation.params, created_by=user_id
    )
    session.add(run)
    session.flush()  # assign run.id
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
    delivery_date: datetime.date,
    fridge_ids: list[int] | None,
    model: str,
    extra_params: dict | None,
    overwrite: bool,
    user_id: int | None,
    session: Session,
) -> ForecastRun:
    """Persist the ONE saved forecast for ``delivery_date`` (D2 save semantics).

    A saved forecast already existing for the key yields ``409 {code:"exists"}``
    unless ``overwrite`` is set, in which case the prior saved run (and its
    results, via ON DELETE CASCADE) is deleted and the fresh run reinserted in a
    single transaction, with an audit row.
    """
    _validate_model(model)
    existing_id = session.execute(
        text(
            "SELECT id FROM forecast_runs "
            "WHERE delivery_date = :d AND is_saved = true"
        ),
        {"d": delivery_date},
    ).scalar()
    if existing_id is not None and not overwrite:
        raise api_error(
            409,
            "exists",
            "A saved forecast already exists for this key; resend with overwrite=true",
            {"delivery_date": delivery_date.isoformat(), "run_id": int(existing_id)},
        )

    computation = _compute_run(
        delivery_date=delivery_date,
        fridge_ids=fridge_ids,
        model=model,
        extra_params=extra_params,
        session=session,
    )

    if existing_id is not None:
        session.execute(
            text("DELETE FROM forecast_runs WHERE id = :id"), {"id": int(existing_id)}
        )
        session.flush()

    day_name = day_name_for_date(delivery_date)
    new_id = session.execute(
        text(
            "INSERT INTO forecast_runs "
            "(delivery_date, model, is_saved, day_name, params, created_by) "
            "VALUES (:d, :model, true, :day_name, CAST(:params AS jsonb), :created_by) "
            "RETURNING id"
        ),
        {
            "d": delivery_date,
            "model": model,
            "day_name": day_name,
            "params": json.dumps(computation.params),
            "created_by": user_id,
        },
    ).scalar_one()
    _insert_results(int(new_id), computation.cells, session)

    record_audit(
        session,
        action="forecast.save.overwrite" if existing_id is not None else "forecast.save",
        entity="forecast_runs",
        entity_id=int(new_id),
        before={"run_id": int(existing_id)} if existing_id is not None else None,
        after={
            "delivery_date": delivery_date.isoformat(),
            "model": model,
            "day_name": day_name,
            "is_saved": True,
        },
        user_id=user_id,
    )
    session.commit()
    return session.get(ForecastRun, int(new_id))


@dataclass(frozen=True)
class RunMeta:
    """The migration-0005 columns the ORM ``ForecastRun`` does not map."""

    model: str
    is_saved: bool
    day_name: str | None


def get_run_meta(run_id: int, session: Session) -> RunMeta:
    """Read ``model`` / ``is_saved`` / ``day_name`` for a run (not on the ORM)."""
    row = session.execute(
        text("SELECT model, is_saved, day_name FROM forecast_runs WHERE id = :id"),
        {"id": run_id},
    ).one()
    return RunMeta(model=row.model, is_saved=bool(row.is_saved), day_name=row.day_name)


def get_saved_run(delivery_date: datetime.date, session: Session) -> ForecastRun | None:
    """Load the saved forecast for a delivery date (import-from-database, D2)."""
    saved_id = session.execute(
        text(
            "SELECT id FROM forecast_runs "
            "WHERE delivery_date = :d AND is_saved = true"
        ),
        {"d": delivery_date},
    ).scalar()
    if saved_id is None:
        return None
    return session.get(ForecastRun, int(saved_id))


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


@dataclass(frozen=True)
class ActualCell:
    """Raw added/sold totals (and their ratio) for one fridge×category."""

    fridge_id: int
    category_id: int
    added_qty: int
    sold_qty: int
    ratio: Decimal | None


def _actual_qty_by_fridge_category(
    table: str,
    timestamp_col: str,
    fridge_ids: list[int],
    window_start: datetime.date,
    delivery_date: datetime.date,
    extra_where: str,
    session: Session,
) -> dict[tuple[int, int], int]:
    """Aggregate event counts per (fridge_id, category_id) over the local-day window.

    Shared by the added (restock) and sold (sales) sides so the window/timezone
    logic - identical to the forecast's :func:`_daily_category_units` - lives once.
    """
    if not fridge_ids:
        return {}
    rows = session.execute(
        text(
            f"SELECT e.fridge_id AS fridge_id, p.category_id AS category_id, "
            f"count(*) AS qty FROM {table} e "
            "JOIN products p ON p.id = e.product_id "
            "WHERE e.fridge_id = ANY(:fridge_ids) "
            f"AND {extra_where} "
            f"AND (e.{timestamp_col} AT TIME ZONE '{_LOCAL_TZ}')::date >= :start "
            f"AND (e.{timestamp_col} AT TIME ZONE '{_LOCAL_TZ}')::date < :end "
            "GROUP BY e.fridge_id, p.category_id"
        ),
        {"fridge_ids": fridge_ids, "start": window_start, "end": delivery_date},
    ).all()
    return {(row.fridge_id, row.category_id): int(row.qty) for row in rows}


def get_actuals(
    *,
    delivery_date: datetime.date,
    fridge_ids: list[int] | None,
    session: Session,
) -> list[ActualCell]:
    """Actual added vs sold per fridge×category over the forecast lookback window.

    Same 3-week (21-day) window and delivery-weekday fridge set the forecast run
    uses. ``added_qty`` counts VALID ADDED ``restock_events``; ``sold_qty`` counts
    non-refunded ``sales_events``. ``ratio`` = sold/added (None when nothing was
    added). Returns only cells with any activity; the caller treats missing keys
    as 0/0. Degrades to an empty list when no fridge is configured for the weekday
    (mirrors an empty forecast rather than raising).
    """
    delivery_weekday = delivery_date.isoweekday()
    window_start = delivery_date - datetime.timedelta(days=_LOOKBACK_DAYS)
    configs = _target_configs(delivery_weekday, fridge_ids, session)
    target_fridge_ids = [config.fridge_id for config in configs]

    added = _actual_qty_by_fridge_category(
        "restock_events",
        "occurred_at",
        target_fridge_ids,
        window_start,
        delivery_date,
        "e.action = 'added' AND e.tag_status = 'valid'",
        session,
    )
    sold = _actual_qty_by_fridge_category(
        "sales_events",
        "sold_at",
        target_fridge_ids,
        window_start,
        delivery_date,
        "e.is_refunded = false",
        session,
    )

    cells: list[ActualCell] = []
    for key in sorted(set(added) | set(sold)):
        added_qty = added.get(key, 0)
        sold_qty = sold.get(key, 0)
        ratio = (
            (Decimal(sold_qty) / Decimal(added_qty)).quantize(Decimal("0.0001"))
            if added_qty > 0
            else None
        )
        cells.append(
            ActualCell(
                fridge_id=key[0],
                category_id=key[1],
                added_qty=added_qty,
                sold_qty=sold_qty,
                ratio=ratio,
            )
        )
    return cells


def get_latest_run(
    delivery_date: datetime.date | None, session: Session
) -> ForecastRun | None:
    stmt = select(ForecastRun)
    if delivery_date is not None:
        stmt = stmt.where(ForecastRun.delivery_date == delivery_date)
    stmt = stmt.order_by(ForecastRun.run_at.desc(), ForecastRun.id.desc()).limit(1)
    return session.execute(stmt).scalars().first()
