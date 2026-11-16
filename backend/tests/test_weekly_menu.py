"""Week menu, sold-first (spec 0008) and stock-aware (spec 0009) replenishment.

The split tests use Mathieu's example from the 22 Oct 2026 call: 15 desserts
forecast for a fridge, ratings 66 / 70 / 75 %, product 2 sold 11 since the last
delivery. API tests reuse the rolled-back ``ctx`` fixture, so nothing persists.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.master import Client, ClientRule, Fridge, ProductTag
from app.models.planning import ForecastResult
from app.services import forecast_service, sales_pace_service, scoring_service
from app.services.menu_allocation_service import rating_weights
from app.services.menu_service import CategorySplit, _residual_add_back, _speed_adjusted_target
from app.services.replenishment_service import (
    LOCAL_TIMEZONE,
    CategorySalesSinceDelivery,
    cut_by_fridge_stock,
    split_category_quantity,
)
from app.services.stock_service import day_name_for_date
from tests.test_workflow_pipeline import (
    DAY_NAME,
    DELIVERY_DATE,
    PREFIX,
    TAG,
    WEEK,
    YEAR,
    _create_fridge,
    _create_product,
    _create_supplier,
    _normal_category_id,
    _two_normal_categories,
    ctx,  # noqa: F401 - pytest fixture
)

MENU_KEY = {"year": YEAR, "week": WEEK, "day_name": DAY_NAME}
WEEK_KEY = {"year": YEAR, "week": WEEK}
MATHIEU_RATINGS = [Decimal("0.66"), Decimal("0.70"), Decimal("0.75")]
MATHIEU_FORECAST = 15
NO_SALES = [0, 0, 0]
DAYS_TO_FILL = 7
STALE_READING_AGE = datetime.timedelta(hours=3)
PREVIOUS_DELIVERY_DATE = DELIVERY_DATE - datetime.timedelta(days=7)
PREVIOUS_DELIVERED_AT = datetime.datetime.combine(
    PREVIOUS_DELIVERY_DATE,
    datetime.time(8),
    tzinfo=LOCAL_TIMEZONE,
)
PREVIOUS_FORECAST = 20
# 84 of the window's 160 hours (Wed 08:00 to the next Wed 00:00) have elapsed, 76 remain:
# 20 x 76 / 160 = 9.5 forecast units are still expected before the next delivery.
HALF_WINDOW_LATER = PREVIOUS_DELIVERED_AT + datetime.timedelta(days=3, hours=12)
MONDAY = 1
EVENING_HOURS = (17, 18)
EXCLUDED_TAG = "contains_pork"


@dataclass(frozen=True)
class SeededProducts:
    fridge_id: int
    category_id: int
    product_ids: list[int]


def test_plain_split_follows_rating():
    quantities = split_category_quantity(
        target=MATHIEU_FORECAST,
        weights=MATHIEU_RATINGS,
        sold_quantities=NO_SALES,
    )

    assert quantities == [5, 5, 5]


def test_sold_first_refills_sold_product_then_splits_rest_over_the_others():
    quantities = split_category_quantity(
        target=MATHIEU_FORECAST,
        weights=MATHIEU_RATINGS,
        sold_quantities=[0, 11, 0],
    )

    assert quantities == [2, 11, 2]


def test_sold_first_splits_remainder_over_all_when_every_product_sold():
    quantities = split_category_quantity(
        target=MATHIEU_FORECAST,
        weights=MATHIEU_RATINGS,
        sold_quantities=[2, 3, 4],
    )

    assert quantities == [4, 5, 6]


def test_sales_above_forecast_are_capped_in_proportion_to_sales():
    quantities = split_category_quantity(
        target=6,
        weights=MATHIEU_RATINGS,
        sold_quantities=[4, 5, 0],
    )

    assert quantities == [3, 3, 0]


def test_stock_cut_delivers_only_what_the_share_needs_beyond_good_units():
    cut_quantities = cut_by_fridge_stock(shares=[6, 6, 6], good_units=[3, 0, 10])

    assert [cut.qty for cut in cut_quantities] == [3, 6, 0]
    assert [cut.reduced_by for cut in cut_quantities] == [3, 0, 6]
    assert [cut.in_fridge_units for cut in cut_quantities] == [3, 0, 10]


def test_sales_speed_factor_follows_the_pace_between_floor_and_ceiling():
    assert sales_pace_service.sales_speed_factor(Decimal("0.80")) == Decimal("0.80")
    assert sales_pace_service.sales_speed_factor(Decimal("1.30")) == Decimal("1.30")
    assert sales_pace_service.sales_speed_factor(Decimal("0.20")) == Decimal("0.50")
    assert sales_pace_service.sales_speed_factor(Decimal("3.10")) == Decimal("2.00")


def test_sales_speed_rounds_half_up():
    assert sales_pace_service.apply_sales_speed_factor(15, Decimal("0.50")) == 8
    assert sales_pace_service.apply_sales_speed_factor(15, Decimal("1.30")) == 20


def test_hourly_profile_weighs_busy_hours_and_skips_closed_days():
    profile = sales_pace_service.HourlySalesProfile(
        source=sales_pace_service.ProfileSource.FRIDGE,
        counts=_evening_sales_counts(),
        active_on_weekends=False,
    )
    monday = _next_weekday(DELIVERY_DATE, MONDAY)
    saturday = monday + datetime.timedelta(days=5)

    assert profile.sales_weight(_local(monday, 8), _local(monday, 9)) == 0
    assert profile.sales_weight(_local(monday, 17), _local(monday, 18)) == 1
    assert profile.sales_weight(_local(monday, 16, 30), _local(monday, 17, 30)) == Decimal("0.5")
    assert profile.sales_weight(_local(saturday, 17), _local(saturday, 19)) == 0


def test_sales_speed_matches_mathieus_cookie_example():
    """12 cookies delivered Monday 08:00, 6 sold by Tuesday noon; cookies sell 17:00-19:00.

    By Tuesday noon one of the two selling evenings is over, so 6 more are expected:
    (6 + 6) / 12 = pace 1.00. A linear spread would have said (6 + 3.6) / 12 = 0.80.
    """
    monday = _next_weekday(DELIVERY_DATE, MONDAY)
    delivered_at = _local(monday, 8)
    sales = CategorySalesSinceDelivery(
        fridge_id=1,
        category_id=1,
        delivered_at=delivered_at,
        sold_qty=6,
    )
    evening_profiles = sales_pace_service.SalesProfiles(
        counts_by_fridge_category={(1, 1): _evening_sales_counts()},
        counts_by_category={},
    )
    no_profiles = sales_pace_service.SalesProfiles(
        counts_by_fridge_category={},
        counts_by_category={},
    )
    speed_inputs = {
        "sales": sales,
        "previous_forecasts": {(monday, 1, 1): Decimal("12")},
        "fill_windows": {
            (1, MONDAY): sales_pace_service.FillWindow(days_to_fill=2, active_on_weekends=True),
        },
        "measured_until": _local(monday + datetime.timedelta(days=1), 12),
        "next_delivery_start": _local(monday + datetime.timedelta(days=2), 0),
    }

    profiled = sales_pace_service._category_sales_speed(profiles=evening_profiles, **speed_inputs)
    linear = sales_pace_service._category_sales_speed(profiles=no_profiles, **speed_inputs)

    assert (profiled.remaining_units, profiled.pace) == (Decimal("6.00"), Decimal("1.00"))
    assert profiled.profile_source == "fridge"
    assert (linear.remaining_units, linear.pace) == (Decimal("3.60"), Decimal("0.80"))
    assert linear.profile_source == "linear"


def test_shelf_life_check_keeps_a_short_lived_product_at_its_unraised_share():
    shelf_life_check = sales_pace_service.ShelfLifeCheck(
        shelf_life_days_by_product={1: 2, 2: 10, 3: None},
        coverage_days_by_fridge={7: 3},
    )

    limited = sales_pace_service.keep_raise_within_shelf_life(
        fridge_id=7,
        product_ids=[1, 2, 3],
        raised_shares=[7, 7, 7],
        unraised_shares=[5, 5, 5],
        shelf_life_check=shelf_life_check,
    )

    assert limited.shares == [5, 7, 7]
    assert limited.holds == [
        sales_pace_service.ShelfLifeHold(
            fridge_id=7,
            product_id=1,
            raised_qty=7,
            kept_qty=5,
            shelf_life_days=2,
            coverage_days=3,
        )
    ]


def test_speed_factor_scales_the_gross_demand_not_the_fridge_stock():
    """Gross 20, 10 good units deducted: half speed needs 10, minus the 10 in stock = 0."""
    stock_deducted = ForecastResult(forecast_qty=Decimal("10"), gross_qty=Decimal("20"))
    saved_before_gross = ForecastResult(forecast_qty=Decimal("15"))

    assert _speed_adjusted_target(stock_deducted, 10, Decimal("0.50")) == 0
    assert _speed_adjusted_target(saved_before_gross, 15, Decimal("0.60")) == 9


def test_negative_score_weighs_zero_and_unscored_weighs_the_mean():
    weights = rating_weights([1, 2, 3], {1: Decimal("-0.20"), 2: Decimal("0.60")})

    assert weights.weights == [Decimal("0"), Decimal("0.60"), Decimal("0.30")]
    assert weights.default_score_product_ids == [3]


def test_sold_first_gives_a_new_product_its_full_rating_share():
    """Product 3 has no score and sold nothing: it keeps the 5 a rating split gives it."""
    category_split = CategorySplit(
        product_ids=[1, 2, 3],
        weights=rating_weights(
            [1, 2, 3],
            {1: MATHIEU_RATINGS[0], 2: MATHIEU_RATINGS[1]},
        ),
        sold_quantities=[0, 11, 0],
    )

    shares = category_split.split(MATHIEU_FORECAST)

    assert shares == [0, 10, 5]
    assert category_split.default_score_ids_with_units(shares) == [3]
    assert category_split.default_score_ids_with_units([5, 10, 0]) == []


def test_save_makes_the_grid_products_the_week_menu_for_every_day(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    category_id = _normal_category_id(session)
    supplier_id = _create_supplier(client, f"{TAG}WeekSup")
    kept_product = _create_product(
        client,
        code=f"{TAG}WK1",
        category_id=category_id,
        supplier_id=supplier_id,
    )
    manual_product = _create_product(
        client,
        code=f"{TAG}WK2",
        category_id=category_id,
        supplier_id=supplier_id,
    )
    fridge_id = _create_fridge(client, f"{TAG}wkfr1")

    save = client.post(
        f"{PREFIX}/menus/save",
        json={
            **MENU_KEY,
            "lines": [
                {"fridge_id": fridge_id, "product_id": kept_product, "qty": 3},
                {"fridge_id": fridge_id, "product_id": manual_product, "qty": 0},
            ],
        },
    )
    assert save.status_code == 200, save.text

    week_menu = client.get(f"{PREFIX}/menus/week", params=WEEK_KEY).json()
    assert week_menu["menu_id"] is not None
    assert _week_product_ids(week_menu) == {kept_product, manual_product}

    other_day = client.get(
        f"{PREFIX}/menus/blank",
        params={**WEEK_KEY, "day_name": "Friday"},
    ).json()
    other_day_product_ids = {product["product_id"] for product in other_day["products"]}
    assert other_day_product_ids == {kept_product, manual_product}
    assert other_day["cells"] == []


def test_category_save_replaces_only_that_part_of_the_week_menu(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    cat_a, cat_b = _two_normal_categories(session)
    supplier_id = _create_supplier(client, f"{TAG}WeekScopeSup")
    product_a = _create_product(
        client,
        code=f"{TAG}WSA",
        category_id=cat_a,
        supplier_id=supplier_id,
    )
    product_b = _create_product(
        client,
        code=f"{TAG}WSB",
        category_id=cat_b,
        supplier_id=supplier_id,
    )
    replacement_a = _create_product(
        client,
        code=f"{TAG}WSA2",
        category_id=cat_a,
        supplier_id=supplier_id,
    )
    fridge_id = _create_fridge(client, f"{TAG}wsfr1")
    first_save = client.post(
        f"{PREFIX}/menus/save",
        json={
            **MENU_KEY,
            "lines": [
                {"fridge_id": fridge_id, "product_id": product_a, "qty": 1},
                {"fridge_id": fridge_id, "product_id": product_b, "qty": 1},
            ],
        },
    )
    assert first_save.status_code == 200, first_save.text

    scoped_save = client.post(
        f"{PREFIX}/menus/save",
        json={
            **MENU_KEY,
            "category_id": cat_a,
            "overwrite": True,
            "lines": [{"fridge_id": fridge_id, "product_id": replacement_a, "qty": 2}],
        },
    )
    assert scoped_save.status_code == 200, scoped_save.text

    week_menu = client.get(f"{PREFIX}/menus/week", params=WEEK_KEY).json()
    assert _week_product_ids(week_menu) == {replacement_a, product_b}


def test_residual_add_back_never_exceeds_what_the_forecast_deducted():
    clamped_at_zero = ForecastResult(
        forecast_qty=Decimal("0"),
        gross_qty=Decimal("5"),
        residual_units=20,
    )
    saved_before_gross = ForecastResult(forecast_qty=Decimal("0"))

    assert _residual_add_back(clamped_at_zero, menu_good_units=20) == 5
    assert _residual_add_back(clamped_at_zero, menu_good_units=3) == 3
    assert _residual_add_back(saved_before_gross, menu_good_units=20) == 20


def test_import_splits_only_over_the_week_menu_products(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    seeded = _seed_three_rated_products(client, session)
    _save_week_menu(client, seeded.fridge_id, [seeded.product_ids[0], seeded.product_ids[2]])
    _seed_saved_forecast(session, seeded.fridge_id, seeded.category_id, MATHIEU_FORECAST)

    imported = client.post(f"{PREFIX}/menus/import-from-forecast", params=MENU_KEY)

    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["used_rating_suggestion"] is False
    assert _cell_quantities(body) == {seeded.product_ids[0]: 7, seeded.product_ids[2]: 8}


def test_import_warns_about_imported_products_the_client_excludes(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    seeded = _seed_three_rated_products(client, session)
    excluded_product_id, _, unimported_product_id = seeded.product_ids
    _save_week_menu(client, seeded.fridge_id, [excluded_product_id, seeded.product_ids[1]])
    _seed_saved_forecast(session, seeded.fridge_id, seeded.category_id, MATHIEU_FORECAST)
    fridge_client = Client(name=f"{TAG}RuleClient")
    session.add(fridge_client)
    session.flush()
    session.get(Fridge, seeded.fridge_id).client_id = fridge_client.id
    session.add_all(
        [
            ProductTag(product_id=excluded_product_id, tag=EXCLUDED_TAG),
            ProductTag(product_id=unimported_product_id, tag=EXCLUDED_TAG),
            ClientRule(client_id=fridge_client.id, rule_type="exclude_tag", tag=EXCLUDED_TAG),
        ]
    )
    session.flush()

    imported = client.post(f"{PREFIX}/menus/import-from-forecast", params=MENU_KEY)

    assert imported.status_code == 200, imported.text
    violations = imported.json()["rule_violations"]
    assert [(item["fridge_id"], item["product_id"], item["tag"]) for item in violations] == [
        (seeded.fridge_id, excluded_product_id, EXCLUDED_TAG)
    ]


def test_import_keeps_a_chosen_product_that_gets_no_quantity(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    seeded = _seed_three_rated_products(client, session)
    _seed_saved_forecast(session, seeded.fridge_id, seeded.category_id, 1)

    imported = client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"product_ids": seeded.product_ids},
    )

    assert imported.status_code == 200, imported.text
    grid = imported.json()["grid"]
    shown_product_ids = {product["product_id"] for product in grid["products"]}
    assert shown_product_ids == set(seeded.product_ids)
    assert sum(cell["qty"] for cell in grid["cells"]) == 1


def test_import_without_a_week_menu_suggests_products_from_ratings(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    seeded = _seed_three_rated_products(client, session)
    _seed_saved_forecast(session, seeded.fridge_id, seeded.category_id, MATHIEU_FORECAST)

    imported = client.post(f"{PREFIX}/menus/import-from-forecast", params=MENU_KEY)

    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["used_rating_suggestion"] is True
    assert sum(cell["qty"] for cell in body["grid"]["cells"]) == MATHIEU_FORECAST


def test_import_lists_forecast_categories_with_no_chosen_product(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    seeded = _seed_three_rated_products(client, session)
    _seeded_category_id, other_category_id = _two_normal_categories(session)
    _seed_saved_forecast(
        session,
        seeded.fridge_id,
        seeded.category_id,
        MATHIEU_FORECAST,
        extra_category_id=other_category_id,
    )

    imported = client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"product_ids": seeded.product_ids},
    )

    assert imported.status_code == 200, imported.text
    assert imported.json()["categories_without_products"] == [other_category_id]


def test_sold_first_import_matches_mathieus_example(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    seeded = _seed_three_rated_products(client, session)
    _save_week_menu(client, seeded.fridge_id, seeded.product_ids)
    _seed_saved_forecast(session, seeded.fridge_id, seeded.category_id, MATHIEU_FORECAST)
    last_delivery = _at_noon(DELIVERY_DATE - datetime.timedelta(days=2))
    _seed_event(
        session,
        table="restock_events",
        fridge_id=seeded.fridge_id,
        product_id=seeded.product_ids[0],
        happened_at=last_delivery,
    )
    sold_before_delivery = last_delivery - datetime.timedelta(hours=1)
    _seed_event(
        session,
        table="sales_events",
        fridge_id=seeded.fridge_id,
        product_id=seeded.product_ids[2],
        happened_at=sold_before_delivery,
    )
    for sale_index in range(11):
        _seed_event(
            session,
            table="sales_events",
            fridge_id=seeded.fridge_id,
            product_id=seeded.product_ids[1],
            happened_at=last_delivery + datetime.timedelta(hours=1, minutes=sale_index),
        )

    sold_first = client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"sold_first": True},
    )
    rating_only = client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"sold_first": False},
    )

    assert sold_first.status_code == 200, sold_first.text
    assert _cell_quantities(sold_first.json()) == dict(zip(seeded.product_ids, [2, 11, 2]))
    assert _cell_quantities(rating_only.json()) == dict(zip(seeded.product_ids, [5, 5, 5]))


def test_fridge_stock_off_keeps_the_plain_split(ctx, monkeypatch):  # noqa: F811
    seeded = _seed_stocked_menu(ctx, monkeypatch, residual_deducted=True)

    imported = ctx.client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"use_fridge_stock": False},
    )

    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert _cell_quantities(body) == dict(zip(seeded.product_ids, [5, 5, 5]))
    assert body["fridge_stock_applied"] is False
    assert body["stock_cuts"] == []


def test_fridge_stock_adds_back_the_forecast_deduction_then_cuts_per_product(
    ctx,  # noqa: F811
    monkeypatch,
):
    """Net 15 + 3 good units added back = 18 split 6/6/6; product 1 holds 3, gets 3."""
    seeded = _seed_stocked_menu(ctx, monkeypatch, residual_deducted=True)

    imported = ctx.client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"use_fridge_stock": True},
    )

    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert _cell_quantities(body) == dict(zip(seeded.product_ids, [3, 6, 6]))
    assert body["fridge_stock_applied"] is True
    assert body["stale_stock_fridge_ids"] == []
    assert body["stock_cuts"] == [
        {
            "fridge_id": seeded.fridge_id,
            "product_id": seeded.product_ids[0],
            "in_fridge_units": 3,
            "reduced_by": 3,
        }
    ]


def test_fridge_stock_cuts_a_forecast_that_deducted_nothing(ctx, monkeypatch):  # noqa: F811
    seeded = _seed_stocked_menu(ctx, monkeypatch, residual_deducted=False)

    imported = ctx.client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"use_fridge_stock": True},
    )

    assert imported.status_code == 200, imported.text
    assert _cell_quantities(imported.json()) == dict(zip(seeded.product_ids, [2, 5, 5]))


def test_fridge_stock_flags_an_old_reading(ctx, monkeypatch):  # noqa: F811
    seeded = _seed_stocked_menu(
        ctx,
        monkeypatch,
        residual_deducted=True,
        reading_age=STALE_READING_AGE,
    )

    imported = ctx.client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"use_fridge_stock": True},
    )

    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["stale_stock_fridge_ids"] == [seeded.fridge_id]
    assert _cell_quantities(body) == dict(zip(seeded.product_ids, [3, 6, 6]))


def test_fridge_stock_is_ignored_for_a_later_delivery(ctx, monkeypatch):  # noqa: F811
    seeded = _seed_stocked_menu(ctx, monkeypatch, residual_deducted=True)
    two_weeks_before = DELIVERY_DATE - datetime.timedelta(days=14)
    monkeypatch.setattr(forecast_service, "_local_today", lambda: two_weeks_before)

    imported = ctx.client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"use_fridge_stock": True},
    )

    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["fridge_stock_applied"] is False
    assert _cell_quantities(body) == dict(zip(seeded.product_ids, [5, 5, 5]))


def test_sales_speed_lowers_a_category_selling_under_its_forecast(ctx, monkeypatch):  # noqa: F811
    """Sold 6 + 9.5 still expected = 15.5 of 20: pace 0.78, so the 15 forecast becomes 12."""
    seeded = _seed_previous_delivery(ctx, monkeypatch, sold_units=6)

    body = _import_with_sales_speed(ctx.client)

    assert body["sales_speed_adjustments"] == [
        {
            "fridge_id": seeded.fridge_id,
            "category_id": seeded.category_id,
            "forecast_units": "20.00",
            "sold_units": 6,
            "remaining_units": "9.50",
            "pace": "0.78",
            "factor": "0.78",
            "profile_source": "linear",
        }
    ]
    assert _cell_quantities(body) == dict(zip(seeded.product_ids, [4, 4, 4]))


def test_sales_speed_raises_a_category_selling_over_its_forecast(ctx, monkeypatch):  # noqa: F811
    """Sold 18 + 9.5 = 27.5 of 20: pace 1.38, so the 15 forecast becomes 21."""
    seeded = _seed_previous_delivery(ctx, monkeypatch, sold_units=18)

    body = _import_with_sales_speed(ctx.client)

    assert [adjustment["factor"] for adjustment in body["sales_speed_adjustments"]] == ["1.38"]
    assert _cell_quantities(body) == dict(zip(seeded.product_ids, [7, 7, 7]))
    assert body["shelf_life_holds"] == []


def test_sales_speed_raise_skips_a_product_that_would_expire(ctx, monkeypatch):  # noqa: F811
    """Product 1 keeps 2 days but the delivery must last 7: it stays at its unraised 5."""
    seeded = _seed_previous_delivery(ctx, monkeypatch, sold_units=18)
    ctx.session.execute(
        text("UPDATE products SET shelf_life_days = 2 WHERE id = :product_id"),
        {"product_id": seeded.product_ids[0]},
    )
    ctx.session.flush()

    body = _import_with_sales_speed(ctx.client)

    assert _cell_quantities(body) == dict(zip(seeded.product_ids, [5, 7, 7]))
    assert body["shelf_life_holds"] == [
        {
            "fridge_id": seeded.fridge_id,
            "product_id": seeded.product_ids[0],
            "raised_qty": 7,
            "kept_qty": 5,
            "shelf_life_days": 2,
            "coverage_days": DAYS_TO_FILL,
        }
    ]


def test_sales_speed_never_goes_below_the_floor(ctx, monkeypatch):  # noqa: F811
    seeded = _seed_previous_delivery(ctx, monkeypatch, sold_units=0)

    body = _import_with_sales_speed(ctx.client)

    assert [adjustment["factor"] for adjustment in body["sales_speed_adjustments"]] == ["0.50"]
    assert sum(_cell_quantities(body).values()) == 8
    assert set(_cell_quantities(body)) <= set(seeded.product_ids)


def test_sales_speed_never_goes_above_the_ceiling(ctx, monkeypatch):  # noqa: F811
    _seed_previous_delivery(ctx, monkeypatch, sold_units=40)

    body = _import_with_sales_speed(ctx.client)

    assert [adjustment["factor"] for adjustment in body["sales_speed_adjustments"]] == ["2.00"]
    assert sum(_cell_quantities(body).values()) == 2 * MATHIEU_FORECAST


def test_sales_speed_skips_too_few_expected_units(ctx, monkeypatch):  # noqa: F811
    """A previous forecast of 8 plans only 8 x 84 / 160 = 4.2 units by now: too few."""
    _seed_previous_delivery(ctx, monkeypatch, sold_units=0, previous_forecast=8)

    body = _import_with_sales_speed(ctx.client)

    assert body["sales_speed_adjustments"] == []
    assert sum(_cell_quantities(body).values()) == MATHIEU_FORECAST


def test_sales_speed_needs_a_previous_saved_forecast(ctx, monkeypatch):  # noqa: F811
    _seed_previous_delivery(ctx, monkeypatch, sold_units=0, previous_forecast=None)

    body = _import_with_sales_speed(ctx.client)

    assert body["sales_speed_adjustments"] == []


def test_sales_speed_off_keeps_the_forecast(ctx, monkeypatch):  # noqa: F811
    _seed_previous_delivery(ctx, monkeypatch, sold_units=2)

    imported = ctx.client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"sales_speed": False},
    )

    assert imported.status_code == 200, imported.text
    assert imported.json()["sales_speed_adjustments"] == []
    assert sum(_cell_quantities(imported.json()).values()) == MATHIEU_FORECAST


def test_sales_speed_skips_weekends_for_a_fridge_closed_on_weekends(
    ctx,  # noqa: F811
    monkeypatch,
):
    """Wed 08:00 to Sun 08:00 is 64 of the window's 112 selling hours, 48 remain.

    20 x 48 / 112 = 8.57 still expected; (7 + 8.57) / 20 = pace 0.78.
    """
    seeded = _seed_previous_delivery(
        ctx,
        monkeypatch,
        sold_units=7,
        measured_at=PREVIOUS_DELIVERED_AT + datetime.timedelta(days=4),
    )
    ctx.session.execute(
        text("UPDATE fridges SET active_on_weekends = false WHERE id = :fridge_id"),
        {"fridge_id": seeded.fridge_id},
    )
    ctx.session.flush()

    body = _import_with_sales_speed(ctx.client)

    adjustment = body["sales_speed_adjustments"][0]
    assert (adjustment["remaining_units"], adjustment["factor"]) == ("8.57", "0.78")


def _seed_previous_delivery(
    ctx,  # noqa: F811
    monkeypatch,
    *,
    sold_units: int,
    previous_forecast: int | None = PREVIOUS_FORECAST,
    measured_at: datetime.datetime = HALF_WINDOW_LATER,
) -> SeededProducts:
    """Mathieu's menu (15 forecast) whose category was delivered a week earlier."""
    monkeypatch.setattr(sales_pace_service, "_now", lambda: measured_at)
    seeded = _seed_three_rated_products(ctx.client, ctx.session)
    _save_week_menu(ctx.client, seeded.fridge_id, seeded.product_ids)
    if previous_forecast is not None:
        _seed_saved_forecast(
            ctx.session,
            seeded.fridge_id,
            seeded.category_id,
            previous_forecast,
            delivery_date=PREVIOUS_DELIVERY_DATE,
        )
    _seed_saved_forecast(ctx.session, seeded.fridge_id, seeded.category_id, MATHIEU_FORECAST)
    _seed_delivery_config(ctx.session, seeded.fridge_id)
    _seed_event(
        ctx.session,
        table="restock_events",
        fridge_id=seeded.fridge_id,
        product_id=seeded.product_ids[0],
        happened_at=PREVIOUS_DELIVERED_AT,
    )
    for sale_index in range(sold_units):
        _seed_event(
            ctx.session,
            table="sales_events",
            fridge_id=seeded.fridge_id,
            product_id=seeded.product_ids[1],
            happened_at=PREVIOUS_DELIVERED_AT + datetime.timedelta(hours=1, minutes=sale_index),
        )
    return seeded


def _import_with_sales_speed(client) -> dict:
    imported = client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params=MENU_KEY,
        json={"sales_speed": True},
    )
    assert imported.status_code == 200, imported.text
    return imported.json()


def _seed_stocked_menu(
    ctx,  # noqa: F811
    monkeypatch,
    *,
    residual_deducted: bool,
    reading_age: datetime.timedelta = datetime.timedelta(0),
) -> SeededProducts:
    """Mathieu's menu, delivered tomorrow; product 1 holds 3 good units of 4 in the fridge.

    The 4 units: two expire after the coverage window, one has no expiry date (counts
    as good) and one expires inside the window (does not count).
    """
    monkeypatch.setattr(
        forecast_service,
        "_local_today",
        lambda: DELIVERY_DATE - datetime.timedelta(days=1),
    )
    seeded = _seed_three_rated_products(ctx.client, ctx.session)
    _save_week_menu(ctx.client, seeded.fridge_id, seeded.product_ids)
    _seed_saved_forecast(
        ctx.session,
        seeded.fridge_id,
        seeded.category_id,
        MATHIEU_FORECAST,
        residual_deducted=residual_deducted,
    )
    _seed_delivery_config(ctx.session, seeded.fridge_id)
    coverage_end = DELIVERY_DATE + datetime.timedelta(days=DAYS_TO_FILL)
    good = _at_noon(coverage_end + datetime.timedelta(days=5))
    expiring = _at_noon(coverage_end - datetime.timedelta(days=2))
    ctx.session.execute(
        text(
            "INSERT INTO fridge_stock "
            "(fridge_id, product_code, product_id, units, expiry_dates, taken_at) "
            "SELECT :fridge_id, code, id, 4, :expiry_dates, now() - :reading_age "
            "FROM products WHERE id = :product_id"
        ),
        {
            "fridge_id": seeded.fridge_id,
            "product_id": seeded.product_ids[0],
            "expiry_dates": [good, good, expiring],
            "reading_age": reading_age,
        },
    )
    ctx.session.flush()
    return seeded


def _seed_delivery_config(session: Session, fridge_id: int) -> None:
    session.execute(
        text(
            "INSERT INTO fridge_delivery_config (fridge_id, weekday, min_daily_qty, days_to_fill) "
            "VALUES (:fridge_id, :weekday, 0, :days_to_fill) "
            "ON CONFLICT (fridge_id, weekday) DO UPDATE SET days_to_fill = :days_to_fill"
        ),
        {
            "fridge_id": fridge_id,
            "weekday": DELIVERY_DATE.isoweekday(),
            "days_to_fill": DAYS_TO_FILL,
        },
    )
    session.flush()


def _seed_three_rated_products(client, session: Session) -> SeededProducts:
    """Three products of one category, named in rating order, rated like Mathieu's example."""
    category_id = _normal_category_id(session)
    supplier_id = _create_supplier(client, f"{TAG}RatedSup")
    product_ids = [
        _create_product(
            client,
            code=f"{TAG}RP{position}",
            category_id=category_id,
            supplier_id=supplier_id,
        )
        for position in (1, 2, 3)
    ]
    period_end = (
        scoring_service.latest_score_period(session, scoring_service.YEARLY_SCORE_WINDOW_DAYS)
        or DELIVERY_DATE
    )
    for product_id, rating in zip(product_ids, MATHIEU_RATINGS):
        session.execute(
            text(
                "INSERT INTO product_scores (product_id, period_end, final_score, window_days) "
                "VALUES (:product_id, :period_end, :rating, :window_days)"
            ),
            {
                "product_id": product_id,
                "period_end": period_end,
                "rating": rating,
                "window_days": int(scoring_service.YEARLY_SCORE_WINDOW_DAYS),
            },
        )
    session.flush()
    fridge_id = _create_fridge(client, f"{TAG}ratedfr")
    return SeededProducts(fridge_id=fridge_id, category_id=category_id, product_ids=product_ids)


def _save_week_menu(client, fridge_id: int, product_ids: list[int]) -> None:
    lines = [
        {"fridge_id": fridge_id, "product_id": product_id, "qty": 0}
        for product_id in product_ids
    ]
    save = client.post(f"{PREFIX}/menus/save", json={**MENU_KEY, "lines": lines})
    assert save.status_code == 200, save.text


def _seed_saved_forecast(
    session: Session,
    fridge_id: int,
    category_id: int,
    forecast_qty: int,
    extra_category_id: int | None = None,
    residual_deducted: bool = False,
    delivery_date: datetime.date = DELIVERY_DATE,
) -> None:
    session.execute(
        text("DELETE FROM forecast_runs WHERE delivery_date = :day AND is_saved"),
        {"day": delivery_date},
    )
    run_id = session.execute(
        text(
            "INSERT INTO forecast_runs (delivery_date, is_saved, day_name, params) "
            "VALUES (:day, true, :day_name, CAST(:params AS jsonb)) RETURNING id"
        ),
        {
            "day": delivery_date,
            "day_name": day_name_for_date(delivery_date),
            "params": json.dumps({"residual_deduction": residual_deducted}),
        },
    ).scalar_one()
    forecast_category_ids = [category_id]
    if extra_category_id is not None:
        forecast_category_ids.append(extra_category_id)
    for forecast_category_id in forecast_category_ids:
        session.execute(
            text(
                "INSERT INTO forecast_results (run_id, fridge_id, category_id, forecast_qty) "
                "VALUES (:run_id, :fridge_id, :category_id, :qty)"
            ),
            {
                "run_id": run_id,
                "fridge_id": fridge_id,
                "category_id": forecast_category_id,
                "qty": forecast_qty,
            },
        )
    session.flush()


def _seed_event(
    session: Session,
    *,
    table: str,
    fridge_id: int,
    product_id: int,
    happened_at: datetime.datetime,
) -> None:
    reference = f"{TAG}{table}-{product_id}-{happened_at.isoformat()}"
    if table == "restock_events":
        statement = (
            "INSERT INTO restock_events (husky_ref, fridge_id, product_id, action, occurred_at) "
            "VALUES (:ref, :fridge_id, :product_id, 'added', :happened_at)"
        )
    else:
        statement = (
            "INSERT INTO sales_events (husky_ref, fridge_id, product_id, sold_at, unit_price) "
            "VALUES (:ref, :fridge_id, :product_id, :happened_at, 250)"
        )
    session.execute(
        text(statement),
        {
            "ref": reference,
            "fridge_id": fridge_id,
            "product_id": product_id,
            "happened_at": happened_at,
        },
    )
    session.flush()


def _at_noon(day: datetime.date) -> datetime.datetime:
    return datetime.datetime(day.year, day.month, day.day, 12, tzinfo=datetime.timezone.utc)


def _week_product_ids(week_menu: dict) -> set[int]:
    product_ids: set[int] = set()
    for category in week_menu["categories"]:
        product_ids.update(category["product_ids"])
    return product_ids


def _cell_quantities(import_body: dict) -> dict[int, int]:
    return {cell["product_id"]: cell["qty"] for cell in import_body["grid"]["cells"]}


def _evening_sales_counts() -> sales_pace_service.SalesCounts:
    """Equal sales every weekday, all of them between 17:00 and 19:00."""
    return sales_pace_service.SalesCounts(
        units_by_weekday=dict.fromkeys(range(1, 8), 1),
        units_by_hour=dict.fromkeys(EVENING_HOURS, 1),
        total_units=sales_pace_service.MIN_PROFILE_UNITS,
    )


def _next_weekday(start: datetime.date, iso_weekday: int) -> datetime.date:
    days_ahead = (iso_weekday - start.isoweekday()) % 7
    return start + datetime.timedelta(days=days_ahead)


def _local(day: datetime.date, hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=LOCAL_TIMEZONE)
