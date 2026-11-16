"""Forecast page: method windows, residual-stock rule, save-what-is-on-screen.

Integration tests run against the testing DB inside one outer transaction that
is rolled back on teardown; seeded names use the ``ZZFC-`` prefix.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.main import app
from app.routers import forecasts as forecasts_router
from app.schemas.masters import ApiException
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
WEEKEND_ISO_WEEKDAYS = (6, 7)
FRIDAY_DELIVERY = DELIVERY_DATE + datetime.timedelta(days=2)


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


@pytest.fixture(autouse=True)
def today_is_delivery_day(monkeypatch):
    """Recent-sales windows end at today: pin today so they end at the delivery date."""
    monkeypatch.setattr(forecast_service, "_local_today", _delivery_day)


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
    window = FORECAST_STRATEGIES[model].sales_window(DELIVERY_DATE, sales_until=DELIVERY_DATE)
    assert window == SalesWindow(start=expected_start, end=expected_end)
    assert window.start.isoweekday() == DELIVERY_WEEKDAY


@pytest.mark.parametrize(
    ("model", "expected_start", "expected_end"),
    [
        ("moving_average_3w", datetime.date(2026, 11, 18), datetime.date(2026, 12, 9)),
        ("moving_average_3m", datetime.date(2026, 9, 9), datetime.date(2026, 12, 9)),
        ("last_year_3w", datetime.date(2025, 11, 26), datetime.date(2025, 12, 17)),
    ],
)
def test_recent_windows_stop_before_today_for_a_later_delivery(
    model: str,
    expected_start: datetime.date,
    expected_end: datetime.date,
):
    """Days that have not happened yet are not days without sales."""
    a_week_before_delivery = DELIVERY_DATE - datetime.timedelta(days=7)
    window = FORECAST_STRATEGIES[model].sales_window(
        DELIVERY_DATE,
        sales_until=a_week_before_delivery,
    )
    assert window == SalesWindow(start=expected_start, end=expected_end)


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
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    coverage_end = DELIVERY_DATE + datetime.timedelta(days=DAYS_TO_FILL)
    good = _noon_utc(coverage_end + datetime.timedelta(days=10))
    expiring = _noon_utc(coverage_end - datetime.timedelta(days=2))
    _seed_fridge_stock(seeded, expiry_dates=[good, good, expiring])

    body = _run(seeded).json()
    assert body["residual_applied"] is True
    # base 3.00 minus the 2 units still good through the coverage window
    assert _cell(seeded, body)["forecast_qty"] == "1.00"


def test_residual_counts_units_without_an_expiry_date(seeded, monkeypatch):
    """A tag with no expiry date is good stock: 1 dated good unit + 2 undated = 3."""
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    good = _noon_utc(DELIVERY_DATE + datetime.timedelta(days=30))
    _seed_fridge_stock(seeded, expiry_dates=[good], units=3)

    body = _run(seeded).json()
    assert _cell(seeded, body)["forecast_qty"] == "0.00"


def test_residual_never_goes_negative(seeded, monkeypatch):
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    good = _noon_utc(DELIVERY_DATE + datetime.timedelta(days=30))
    _seed_fridge_stock(seeded, expiry_dates=[good] * 10)

    body = _run(seeded).json()
    assert _cell(seeded, body)["forecast_qty"] == "0.00"


def test_later_delivery_skips_residual_and_averages_the_last_21_days_until_today(
    seeded,
    monkeypatch,
):
    """Stock is only known now, so a delivery past the next one gets no deduction."""
    two_weeks_before = DELIVERY_DATE - datetime.timedelta(days=14)
    monkeypatch.setattr(forecast_service, "_local_today", lambda: two_weeks_before)
    _seed_daily_sales(seeded, last_day=two_weeks_before, days=21)
    good = _noon_utc(DELIVERY_DATE + datetime.timedelta(days=30))
    _seed_fridge_stock(seeded, expiry_dates=[good] * 2)

    body = _run(seeded).json()
    assert body["residual_applied"] is False
    assert body["window_end"] == two_weeks_before.isoformat()
    # 21 sales / 21 days * 3 days: the 14 days still to come are not counted as empty
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


@pytest.mark.parametrize(
    ("active_on_weekends", "expected_qty"),
    [
        # 15 weekday sales / 21 window days (6 empty weekend days) * 3 days = 2.14
        (True, "2.14"),
        # weekends leave the window: 15 sales / 15 weekdays * 3 days = 3.00
        (False, "3.00"),
    ],
)
def test_weekend_flag_drops_weekend_days_from_sales_window(
    seeded,
    active_on_weekends: bool,
    expected_qty: str,
):
    update = seeded.client.put(
        f"{PREFIX}/fridges/{seeded.fridge_id}",
        json={"active_on_weekends": active_on_weekends},
    )
    assert update.status_code == 200, update.text
    assert update.json()["active_on_weekends"] is active_on_weekends
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21, skip_weekends=True)

    body = _run(seeded).json()
    fridge_params = body["params"]["fridge_config"][str(seeded.fridge_id)]
    assert fridge_params["active_on_weekends"] is active_on_weekends
    assert _cell(seeded, body)["forecast_qty"] == expected_qty


@pytest.mark.parametrize(
    ("active_on_weekends", "expected_qty"),
    [
        # Friday covers Fri/Sat/Sun: 15 sales / 21 days * 3 days = 2.14
        (True, Decimal("2.14")),
        # only Friday is a selling day: 15 sales / 15 weekdays * 1 day = 1.00
        (False, Decimal("1.00")),
    ],
)
def test_weekend_flag_counts_only_weekdays_to_fill(
    active_on_weekends: bool,
    expected_qty: Decimal,
):
    window = _three_week_window(FRIDAY_DELIVERY)
    window_days = [window.start + datetime.timedelta(days=offset) for offset in range(window.days)]
    category_id = 1
    weekday_sales = {
        (day, category_id): 1
        for day in window_days
        if day.isoweekday() not in WEEKEND_ISO_WEEKDAYS
    }
    config = forecast_service._FridgeConfig(
        fridge_id=1,
        min_daily_qty=0,
        days_to_fill=DAYS_TO_FILL,
        active_on_weekends=active_on_weekends,
    )

    cells = forecast_service._compute_cells(
        config=config,
        day_cat_units=weekday_sales,
        window=window,
        selling_calendar=forecast_service._SellingCalendar(
            active_on_weekends=active_on_weekends,
            bank_holidays=frozenset(),
        ),
        selling_days_to_fill=forecast_service.count_selling_days(
            FRIDAY_DELIVERY,
            DAYS_TO_FILL,
            active_on_weekends,
        ),
        category_ids=[category_id],
        margins_by_id={category_id: Decimal("0")},
        residual_by_category={},
    )
    assert cells[0].forecast_qty == expected_qty


def test_bank_holiday_is_not_a_selling_day():
    holiday = FRIDAY_DELIVERY + datetime.timedelta(days=3)  # the Monday after
    with_holiday = forecast_service.count_selling_days(
        FRIDAY_DELIVERY,
        7,
        True,
        frozenset({holiday}),
    )
    assert with_holiday == 6
    assert not forecast_service.is_selling_day(holiday, True, frozenset({holiday}))


def test_bank_holiday_sales_leave_the_window_and_stock_splits_gross_from_net():
    window = _three_week_window(DELIVERY_DATE)
    window_days = [window.start + datetime.timedelta(days=offset) for offset in range(window.days)]
    category_id = 1
    holiday = window_days[0]
    daily_sales = {(day, category_id): 1 for day in window_days}
    config = forecast_service._FridgeConfig(
        fridge_id=1,
        min_daily_qty=0,
        days_to_fill=DAYS_TO_FILL,
        active_on_weekends=True,
    )

    cells = forecast_service._compute_cells(
        config=config,
        day_cat_units=daily_sales,
        window=window,
        selling_calendar=forecast_service._SellingCalendar(
            active_on_weekends=True,
            bank_holidays=frozenset({holiday}),
        ),
        selling_days_to_fill=DAYS_TO_FILL,
        category_ids=[category_id],
        margins_by_id={category_id: Decimal("0")},
        residual_by_category={category_id: 2},
    )
    # 20 sales / 20 selling days * 3 days = 3.00 gross; 2 units in the fridge leave 1.00
    assert cells[0].valid_days == 20
    assert cells[0].no_info_days == 0
    assert cells[0].gross_qty == Decimal("3.00")
    assert cells[0].residual_units == 2
    assert cells[0].forecast_qty == Decimal("1.00")


@pytest.mark.parametrize(
    ("weekdays", "expected"),
    [
        (None, None),
        ("", None),
        ("4,1, 2,3", [1, 2, 3, 4]),
        ("2,2", [2]),
    ],
)
def test_compare_weekdays_are_parsed(weekdays: str | None, expected: list[int] | None):
    assert forecasts_router._parse_weekdays(weekdays) == expected


@pytest.mark.parametrize("weekdays", ["0", "8", "mon", "1,,2"])
def test_compare_weekdays_reject_bad_input(weekdays: str):
    with pytest.raises(ApiException):
        forecasts_router._parse_weekdays(weekdays)


def test_compare_window_needs_both_ends_and_a_positive_length():
    start = datetime.date(2026, 10, 19)
    assert forecasts_router._compare_window(None, None) is None
    window = forecasts_router._compare_window(start, start + datetime.timedelta(days=4))
    assert window == SalesWindow(start=start, end=start + datetime.timedelta(days=4))
    with pytest.raises(ApiException):
        forecasts_router._compare_window(start, None)
    with pytest.raises(ApiException):
        forecasts_router._compare_window(start, start)


def test_run_reports_gross_stock_and_sales_per_fridge(seeded, monkeypatch):
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    good = _noon_utc(DELIVERY_DATE + datetime.timedelta(days=30))
    _seed_fridge_stock(seeded, expiry_dates=[good, good])

    body = _run(seeded).json()
    cell = _cell(seeded, body)
    assert (cell["gross_qty"], cell["residual_units"], cell["forecast_qty"]) == (
        "3.00",
        2,
        "1.00",
    )
    fridge_sales = {row["fridge_id"]: row["sold_units"] for row in body["window_sales_by_fridge"]}
    assert fridge_sales[seeded.fridge_id] == 21
    fridge_params = body["params"]["fridge_config"][str(seeded.fridge_id)]
    assert fridge_params["selling_days_to_fill"] == DAYS_TO_FILL


def test_bank_holiday_in_window_and_on_delivery_day(seeded):
    window = _three_week_window(DELIVERY_DATE)
    _clear_bank_holidays(seeded, window.start, DELIVERY_DATE + datetime.timedelta(days=7))
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    for holiday_date in (window.start, DELIVERY_DATE):
        created = seeded.client.post(
            f"{PREFIX}/forecasts/bank-holidays",
            json={"holiday_date": holiday_date.isoformat(), "label": f"{TAG}holiday"},
        )
        assert created.status_code == 201, created.text

    body = _run(seeded).json()
    assert body["delivery_bank_holiday"] == f"{TAG}holiday"
    assert body["params"]["excluded_bank_holidays"] == [
        window.start.isoformat(),
        DELIVERY_DATE.isoformat(),
    ]
    assert body["params"]["fridge_config"][str(seeded.fridge_id)]["selling_days_to_fill"] == 2
    # 20 sales / 20 selling days * 2 selling days to fill = 2.00
    assert _cell(seeded, body)["forecast_qty"] == "2.00"


def test_bank_holiday_crud(seeded):
    holiday_date = datetime.date(2026, 12, 28)
    _clear_bank_holidays(seeded, holiday_date, holiday_date)
    url = f"{PREFIX}/forecasts/bank-holidays"
    body = {"holiday_date": holiday_date.isoformat(), "label": f"  {TAG}extra  "}
    created = seeded.client.post(url, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["label"] == f"{TAG}extra"
    assert seeded.client.post(url, json=body).status_code == 409

    listed = seeded.client.get(url, params={"year": 2026}).json()
    assert holiday_date.isoformat() in [row["holiday_date"] for row in listed]

    assert seeded.client.delete(f"{url}/{holiday_date.isoformat()}").status_code == 204
    assert seeded.client.delete(f"{url}/{holiday_date.isoformat()}").status_code == 404


def test_saved_list_shows_saved_runs_only(seeded):
    run = _run(seeded).json()
    listed_before = seeded.client.get(f"{PREFIX}/forecasts/saved-list", params={"year": YEAR})
    assert run["run_id"] not in [row["run_id"] for row in listed_before.json()]

    saved = seeded.client.post(
        f"{PREFIX}/forecasts/save",
        json={"run_id": run["run_id"], "cells": _screen_cells(run, seeded, "1")},
    )
    assert saved.status_code == 200, saved.text
    listed = seeded.client.get(f"{PREFIX}/forecasts/saved-list", params={"year": YEAR}).json()
    row = next(row for row in listed if row["run_id"] == run["run_id"])
    assert (row["iso_year"], row["week_no"], row["day_name"]) == (YEAR, WEEK, DAY_NAME)


def test_actuals_compare_window_keeps_only_chosen_weekdays(seeded):
    _seed_daily_sales(seeded, last_day=DELIVERY_DATE, days=21)
    compare_start = DELIVERY_DATE - datetime.timedelta(days=14)
    resp = seeded.client.get(
        f"{PREFIX}/forecasts/actuals",
        params={
            "year": YEAR,
            "week": WEEK,
            "day_name": DAY_NAME,
            "start": compare_start.isoformat(),
            "end": (compare_start + datetime.timedelta(days=7)).isoformat(),
            "weekdays": "1,2,3,4",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["weekdays"] == [1, 2, 3, 4]
    cell = next(
        actual
        for actual in body["cells"]
        if actual["fridge_id"] == seeded.fridge_id and actual["category_id"] == seeded.category_id
    )
    assert cell["sold_qty"] == 4


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


def _seed_daily_sales(
    seeded,
    *,
    last_day: datetime.date,
    days: int,
    skip_weekends: bool = False,
) -> None:
    """One sale per day for ``days`` days ending the day before ``last_day``."""
    for offset in range(1, days + 1):
        day = last_day - datetime.timedelta(days=offset)
        if skip_weekends and day.isoweekday() in WEEKEND_ISO_WEEKDAYS:
            continue
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


def _seed_fridge_stock(
    seeded,
    *,
    expiry_dates: list[datetime.datetime],
    units: int | None = None,
) -> None:
    """``units`` above ``len(expiry_dates)`` adds units whose tag has no expiry date."""
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
            "units": len(expiry_dates) if units is None else units,
            "expiry": expiry_dates,
        },
    )
    seeded.session.flush()


def _clear_bank_holidays(
    seeded,
    first_day: datetime.date,
    last_day: datetime.date,
) -> None:
    """Seeded holidays would shift the expected numbers; the outer rollback restores them."""
    seeded.session.execute(
        text("DELETE FROM bank_holidays WHERE holiday_date BETWEEN :first_day AND :last_day"),
        {"first_day": first_day, "last_day": last_day},
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


def _delivery_day() -> datetime.date:
    return DELIVERY_DATE


def _three_week_window(delivery_date: datetime.date) -> SalesWindow:
    return FORECAST_STRATEGIES["moving_average_3w"].sales_window(
        delivery_date,
        sales_until=delivery_date,
    )
