"""Forecast page: method windows, residual-stock rule, save-what-is-on-screen.

Integration tests run against the testing DB inside one outer transaction that
is rolled back on teardown; seeded names use the ``ZZFC-`` prefix.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.main import app
from app.services import forecast_service
from app.services.forecast.strategies import FORECAST_STRATEGIES, SalesWindow
from tests import ensure_test_admin_user

PREFIX = "/api/v1"
TAG = "ZZFC-"

# sales_events partitions in the testing DB end at 2027-01.
YEAR, WEEK, DAY_NAME = 2026, 51, "Wednesday"
DELIVERY_DATE = datetime.date.fromisocalendar(YEAR, WEEK, 3)  # 2026-12-16
DELIVERY_WEEKDAY = DELIVERY_DATE.isoweekday()
DAYS_TO_FILL = 3
LAST_YEAR_SHIFT = datetime.timedelta(days=364)


@pytest.fixture()
def ctx():
    connection = engine.connect()
    outer = connection.begin()
    ensure_test_admin_user(connection)
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    try:
        yield SimpleNamespace(client=client, session=session)
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture()
def seeded(ctx):
    """One fridge delivering on DELIVERY_WEEKDAY (days_to_fill 3) and one product."""
    client, session = ctx.client, ctx.session
    session.execute(
        text("DELETE FROM forecast_runs WHERE delivery_date = :delivery_date"),
        {"delivery_date": DELIVERY_DATE},
    )
    category_id = _normal_category_id(session)
    supplier = client.post(f"{PREFIX}/suppliers", json={"name": f"{TAG}Sup"})
    assert supplier.status_code == 201, supplier.text
    product = client.post(
        f"{PREFIX}/products",
        json={
            "code": f"{TAG}P1",
            "name": f"{TAG}P1",
            "category_id": category_id,
            "supplier_id": supplier.json()["id"],
            "purchase_price": "1.00",
            "sales_price": "2.50",
            "vat_rate": "0.06",
        },
    )
    assert product.status_code == 201, product.text
    fridge = client.post(
        f"{PREFIX}/fridges",
        json={"husky_id": f"{TAG}fr1", "friendly_name": f"{TAG}fr1"},
    )
    assert fridge.status_code == 201, fridge.text
    fridge_id = fridge.json()["id"]
    second_weekday = ((DELIVERY_WEEKDAY + DAYS_TO_FILL - 1) % 7) + 1
    config = client.put(
        f"{PREFIX}/fridges/{fridge_id}/delivery-config",
        json={
            "items": [
                {"weekday": DELIVERY_WEEKDAY, "min_daily_qty": 0},
                {"weekday": second_weekday, "min_daily_qty": 0},
            ]
        },
    )
    assert config.status_code == 200, config.text
    return SimpleNamespace(
        client=client,
        session=session,
        category_id=category_id,
        product_id=product.json()["id"],
        product_code=f"{TAG}P1",
        fridge_id=fridge_id,
    )


@pytest.mark.parametrize(
    ("model", "expected_start", "expected_end"),
    [
        ("moving_average_3w", datetime.date(2026, 11, 25), datetime.date(2026, 12, 16)),
        ("moving_average_3m", datetime.date(2026, 9, 16), datetime.date(2026, 12, 16)),
        ("last_year_3w", datetime.date(2025, 11, 26), datetime.date(2025, 12, 17)),
        ("last_year_3m", datetime.date(2025, 9, 17), datetime.date(2025, 12, 17)),
    ],
)
def test_strategy_sales_window(
    model: str,
    expected_start: datetime.date,
    expected_end: datetime.date,
):
    window = FORECAST_STRATEGIES[model].sales_window(DELIVERY_DATE)
    assert window == SalesWindow(start=expected_start, end=expected_end)
    assert window.start.isoweekday() == DELIVERY_WEEKDAY


def test_models_endpoint_lists_four_methods(ctx):
    resp = ctx.client.get(f"{PREFIX}/forecasts/models")
    assert resp.status_code == 200, resp.text
    assert [model["code"] for model in resp.json()] == [
        "moving_average_3w",
        "moving_average_3m",
        "last_year_3w",
        "last_year_3m",
    ]


def test_unknown_model_is_rejected(seeded):
    resp = _run(seeded, model="moving_average_9y")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_last_year_method_reads_last_years_window(seeded):
    last_year_delivery = DELIVERY_DATE - LAST_YEAR_SHIFT
    _seed_daily_sales(seeded, last_day=last_year_delivery, days=21)

    this_year = _run(seeded, model="moving_average_3w").json()
    assert _cell(seeded, this_year)["forecast_qty"] == "0.00"
    assert this_year["window_sales_units"] == 0

    last_year = _run(seeded, model="last_year_3w").json()
    assert last_year["model"] == "last_year_3w"
    assert last_year["window_start"] == "2025-11-26"
    assert last_year["window_end"] == "2025-12-17"
    assert last_year["window_sales_units"] == 21
    # 21 sales / 21 days * days_to_fill 3 = 3.00
    assert _cell(seeded, last_year)["forecast_qty"] == "3.00"


def test_three_month_method_averages_over_91_days(seeded):
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    body = _run(seeded, model="moving_average_3m").json()
    assert body["params"]["window_days"] == 91
    # 21 valid sale days + 70 no-info days: 21 / 91 * 3 = 0.69
    assert _cell(seeded, body)["forecast_qty"] == "0.69"


def test_actuals_use_the_method_window(seeded):
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE - LAST_YEAR_SHIFT, days=21)
    resp = seeded.client.get(
        f"{PREFIX}/forecasts/actuals",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME, "model": "last_year_3w"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["window_start"], body["window_end"]) == ("2025-11-26", "2025-12-17")
    cell = next(
        actual
        for actual in body["cells"]
        if actual["fridge_id"] == seeded.fridge_id and actual["category_id"] == seeded.category_id
    )
    assert cell["sold_qty"] == 21


def test_new_run_replaces_earlier_unsaved_runs(seeded):
    first = _run(seeded).json()
    second = _run(seeded).json()
    assert seeded.client.get(f"{PREFIX}/forecasts/runs/{first['run_id']}").status_code == 404
    assert seeded.client.get(f"{PREFIX}/forecasts/runs/{second['run_id']}").status_code == 200


def test_save_persists_the_quantities_on_screen(seeded):
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    run = _run(seeded).json()
    edited_cells = _screen_cells(run, seeded, edited_qty="7.25")

    saved = seeded.client.post(
        f"{PREFIX}/forecasts/save",
        json={"run_id": run["run_id"], "cells": edited_cells},
    )
    assert saved.status_code == 200, saved.text
    saved_body = saved.json()
    assert saved_body["run_id"] == run["run_id"]
    assert saved_body["is_saved"] is True
    assert _cell(seeded, saved_body)["forecast_qty"] == "7.25"

    loaded = seeded.client.get(
        f"{PREFIX}/forecasts/saved",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME},
    )
    assert loaded.status_code == 200, loaded.text
    assert _cell(seeded, loaded.json())["forecast_qty"] == "7.25"


def test_save_persists_every_edited_cell(seeded):
    run = _run(seeded).json()
    assert len(run["results"]) > 1
    edited_cells = []
    for position, result in enumerate(run["results"]):
        edited_cells.append(
            {
                "fridge_id": result["fridge_id"],
                "category_id": result["category_id"],
                "forecast_qty": f"{position + 1}.25",
            }
        )

    saved = seeded.client.post(
        f"{PREFIX}/forecasts/save",
        json={"run_id": run["run_id"], "cells": edited_cells},
    )
    assert saved.status_code == 200, saved.text

    loaded = seeded.client.get(
        f"{PREFIX}/forecasts/saved",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME},
    )
    assert loaded.status_code == 200, loaded.text
    expected_qty_by_key = {
        (cell["fridge_id"], cell["category_id"]): cell["forecast_qty"]
        for cell in edited_cells
    }
    loaded_qty_by_key = {
        (result["fridge_id"], result["category_id"]): result["forecast_qty"]
        for result in loaded.json()["results"]
    }
    assert loaded_qty_by_key == expected_qty_by_key


def test_save_keeps_last_value_of_a_duplicated_cell(seeded):
    run = _run(seeded).json()
    first_cells = _screen_cells(run, seeded, "4")
    last_cells = _screen_cells(run, seeded, "9")

    saved = seeded.client.post(
        f"{PREFIX}/forecasts/save",
        json={"run_id": run["run_id"], "cells": first_cells + last_cells},
    )

    assert saved.status_code == 200, saved.text
    assert _cell(seeded, saved.json())["forecast_qty"] == "9.00"

def test_save_over_existing_needs_overwrite(seeded):
    first_run = _run(seeded).json()
    first_save = seeded.client.post(
        f"{PREFIX}/forecasts/save",
        json={"run_id": first_run["run_id"], "cells": _screen_cells(first_run, seeded, "1")},
    )
    assert first_save.status_code == 200, first_save.text

    second_run = _run(seeded).json()
    second_body = {"run_id": second_run["run_id"], "cells": _screen_cells(second_run, seeded, "2")}
    conflict = seeded.client.post(f"{PREFIX}/forecasts/save", json=second_body)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "exists"

    overwritten = seeded.client.post(
        f"{PREFIX}/forecasts/save",
        json={**second_body, "overwrite": True},
    )
    assert overwritten.status_code == 200, overwritten.text
    assert _cell(seeded, overwritten.json())["forecast_qty"] == "2.00"
    old_run = seeded.client.get(f"{PREFIX}/forecasts/runs/{first_run['run_id']}")
    assert old_run.status_code == 404


def test_save_rejects_cells_outside_the_run_and_writes_nothing(seeded):
    run = _run(seeded).json()
    outside_cell = {"fridge_id": -1, "category_id": seeded.category_id, "forecast_qty": "1"}
    edited_cells = _screen_cells(run, seeded, "8")

    resp = seeded.client.post(
        f"{PREFIX}/forecasts/save",
        json={"run_id": run["run_id"], "cells": edited_cells + [outside_cell]},
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
    stored_run = seeded.client.get(f"{PREFIX}/forecasts/runs/{run['run_id']}")
    assert stored_run.status_code == 200, stored_run.text
    assert _cell(seeded, stored_run.json())["forecast_qty"] == _cell(seeded, run)["forecast_qty"]
    saved = seeded.client.get(
        f"{PREFIX}/forecasts/saved",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME},
    )
    assert saved.status_code == 404


def test_save_rejects_negative_quantity(seeded):
    run = _run(seeded).json()
    resp = seeded.client.post(
        f"{PREFIX}/forecasts/save",
        json={"run_id": run["run_id"], "cells": _screen_cells(run, seeded, "-1")},
    )
    assert resp.status_code == 422


def test_residual_stock_deducted_for_next_delivery(seeded, monkeypatch):
    """Current fridge stock good through the coverage window is deducted (slide 5)."""
    monkeypatch.setattr(forecast_service, "_local_today", _day_before_delivery)
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    coverage_end = DELIVERY_DATE + datetime.timedelta(days=DAYS_TO_FILL)
    good = _noon_utc(coverage_end + datetime.timedelta(days=10))
    expiring = _noon_utc(coverage_end - datetime.timedelta(days=2))
    _seed_fridge_stock(seeded, expiry_dates=[good, good, expiring])

    body = _run(seeded).json()
    assert body["residual_applied"] is True
    # base 3.00 minus the 2 units still good through the coverage window
    assert _cell(seeded, body)["forecast_qty"] == "1.00"


def test_residual_never_goes_negative(seeded, monkeypatch):
    monkeypatch.setattr(forecast_service, "_local_today", _day_before_delivery)
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    good = _noon_utc(DELIVERY_DATE + datetime.timedelta(days=30))
    _seed_fridge_stock(seeded, expiry_dates=[good] * 10)

    body = _run(seeded).json()
    assert _cell(seeded, body)["forecast_qty"] == "0.00"


def test_residual_skipped_for_later_delivery_dates(seeded, monkeypatch):
    """Stock is only known now, so a delivery past the next one gets no deduction."""
    two_weeks_before = DELIVERY_DATE - datetime.timedelta(days=14)
    monkeypatch.setattr(forecast_service, "_local_today", lambda: two_weeks_before)
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    good = _noon_utc(DELIVERY_DATE + datetime.timedelta(days=30))
    _seed_fridge_stock(seeded, expiry_dates=[good] * 2)

    body = _run(seeded).json()
    assert body["residual_applied"] is False
    assert _cell(seeded, body)["forecast_qty"] == "3.00"


def test_category_without_products_or_sales_is_hidden(seeded):
    empty_category_id = seeded.session.execute(
        text(
            "INSERT INTO categories (name, display_order, dispatch_print_order) "
            "VALUES (:name, 998, (SELECT max(dispatch_print_order) + 1 FROM categories)) "
            "RETURNING id"
        ),
        {"name": f"{TAG}Empty"},
    ).scalar_one()
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=1)

    body = _run(seeded).json()
    assert empty_category_id in body["hidden_category_ids"]
    assert seeded.category_id not in body["hidden_category_ids"]


def _run(seeded, model: str = "moving_average_3w"):
    return seeded.client.post(
        f"{PREFIX}/forecasts/run",
        json={
            "delivery_date": DELIVERY_DATE.isoformat(),
            "fridge_ids": [seeded.fridge_id],
            "model": model,
        },
    )


def _cell(seeded, run_body: dict) -> dict:
    return next(
        result
        for result in run_body["results"]
        if result["fridge_id"] == seeded.fridge_id and result["category_id"] == seeded.category_id
    )


def _screen_cells(run_body: dict, seeded, edited_qty: str) -> list[dict]:
    """Every cell of the run, with the seeded cell set to ``edited_qty``."""
    cells = []
    for result in run_body["results"]:
        is_edited_cell = (
            result["fridge_id"] == seeded.fridge_id
            and result["category_id"] == seeded.category_id
        )
        cells.append(
            {
                "fridge_id": result["fridge_id"],
                "category_id": result["category_id"],
                "forecast_qty": edited_qty if is_edited_cell else result["forecast_qty"],
            }
        )
    return cells


def _seed_daily_sales(seeded, *, last_day: datetime.date, days: int) -> None:
    """One sale per day for ``days`` days ending the day before ``last_day``."""
    for offset in range(1, days + 1):
        day = last_day - datetime.timedelta(days=offset)
        seeded.session.execute(
            text(
                "INSERT INTO sales_events (husky_ref, fridge_id, product_id, sold_at, "
                "unit_price, is_refunded) VALUES (:ref, :fridge, :product, :sold_at, 250, false)"
            ),
            {
                "ref": f"{TAG}sale-{last_day.isoformat()}-{offset}",
                "fridge": seeded.fridge_id,
                "product": seeded.product_id,
                "sold_at": _noon_utc(day),
            },
        )
    seeded.session.flush()


def _seed_fridge_stock(seeded, *, expiry_dates: list[datetime.datetime]) -> None:
    seeded.session.execute(
        text(
            "INSERT INTO fridge_stock "
            "(fridge_id, product_code, product_id, units, expiry_dates, taken_at) "
            "VALUES (:fridge, :code, :product, :units, :expiry, now())"
        ),
        {
            "fridge": seeded.fridge_id,
            "code": seeded.product_code,
            "product": seeded.product_id,
            "units": len(expiry_dates),
            "expiry": expiry_dates,
        },
    )
    seeded.session.flush()


def _normal_category_id(session: Session) -> int:
    return session.execute(
        text(
            "SELECT id FROM categories "
            "WHERE lower(name) NOT LIKE '%drink%' AND lower(name) NOT LIKE '%snack%' "
            "ORDER BY id LIMIT 1"
        )
    ).scalar_one()


def _noon_utc(day: datetime.date) -> datetime.datetime:
    return datetime.datetime(day.year, day.month, day.day, 12, tzinfo=datetime.timezone.utc)


def _day_before_delivery() -> datetime.date:
    return DELIVERY_DATE - datetime.timedelta(days=1)
