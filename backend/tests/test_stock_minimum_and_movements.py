"""Stock page: newest-first movements, warehouse minimum + low-stock alerts, inactive codes."""

from __future__ import annotations

from sqlalchemy import text

from app.husky.sync import utcnow
from app.services.low_stock_service import refresh_low_stock_alerts
from tests.test_ops_routers import (
    PREFIX,
    TAG,
    _category_ids,
    _create_fridge,
    _create_product,
    _seed_stock,
    ctx,  # noqa: F401 - pytest fixture
)

MOVEMENTS_URL = f"{PREFIX}/stock/movements"
BALANCES_URL = f"{PREFIX}/stock/balances"


def _minimum_url(product_id: int) -> str:
    return f"{PREFIX}/stock/products/{product_id}/minimum"


def _open_low_stock_alerts(ctx, product_id: int) -> list:  # noqa: F811
    return ctx.session.execute(
        text(
            "SELECT status, payload FROM alerts "
            "WHERE alert_type = 'low_stock' AND (payload->>'product_id')::int = :product "
            "ORDER BY id"
        ),
        {"product": product_id},
    ).all()


def _create_drink(ctx, code: str) -> int:  # noqa: F811
    return _create_product(
        ctx.client,
        code=f"{TAG}{code}",
        category_id=_category_ids(ctx.session)["drinks"],
    )


def test_movements_are_newest_first_with_older_pages(ctx):  # noqa: F811
    product_id = _create_drink(ctx, "MOV-1")
    _seed_stock(ctx.client, product_id, 1)
    _seed_stock(ctx.client, product_id, 2)
    _seed_stock(ctx.client, product_id, 3)

    first_page = ctx.client.get(
        MOVEMENTS_URL,
        params={"product_id": product_id, "limit": 2},
    ).json()
    older_page = ctx.client.get(
        MOVEMENTS_URL,
        params={
            "product_id": product_id,
            "limit": 2,
            "before_id": first_page["next_before_id"],
        },
    ).json()

    assert [movement["qty"] for movement in first_page["items"]] == [3, 2]
    assert [movement["qty"] for movement in older_page["items"]] == [1]
    assert older_page["next_before_id"] is None


def test_setting_a_minimum_opens_and_removing_it_resolves_the_alert(ctx):  # noqa: F811
    product_id = _create_drink(ctx, "MIN-1")
    _seed_stock(ctx.client, product_id, 5)

    response = ctx.client.put(_minimum_url(product_id), json={"min_stock_qty": 12})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "product_id": product_id,
        "min_stock_qty": 12,
        "physical_qty": 5,
        "is_low_stock": True,
    }
    [alert] = _open_low_stock_alerts(ctx, product_id)
    assert alert.status == "open"
    assert "has 5 in the warehouse, below the minimum of 12" in alert.payload["message"]

    ctx.client.put(_minimum_url(product_id), json={"min_stock_qty": None})

    [alert] = _open_low_stock_alerts(ctx, product_id)
    assert alert.status == "resolved"


def test_low_stock_check_refresh_opens_updates_and_resolves(ctx):  # noqa: F811
    product_id = _create_drink(ctx, "MIN-2")
    product_without_minimum = _create_drink(ctx, "MIN-3")
    ctx.session.execute(
        text("UPDATE products SET min_stock_qty = 10 WHERE id = :product"),
        {"product": product_id},
    )
    _seed_stock(ctx.client, product_id, 4)
    _seed_stock(ctx.client, product_without_minimum, 1)

    refresh_low_stock_alerts(ctx.session)
    refresh_low_stock_alerts(ctx.session)

    [alert] = _open_low_stock_alerts(ctx, product_id)
    assert alert.status == "open"
    assert alert.payload["physical_qty"] == 4
    assert _open_low_stock_alerts(ctx, product_without_minimum) == []

    _seed_stock(ctx.client, product_id, 20)
    refresh_low_stock_alerts(ctx.session)

    [alert] = _open_low_stock_alerts(ctx, product_id)
    assert alert.status == "resolved"


def test_minimum_rejects_negative_and_unknown_product(ctx):  # noqa: F811
    product_id = _create_drink(ctx, "MIN-4")

    negative = ctx.client.put(_minimum_url(product_id), json={"min_stock_qty": -1})
    unknown = ctx.client.put(_minimum_url(999_999_999), json={"min_stock_qty": 3})

    assert negative.status_code == 422
    assert unknown.status_code == 404


def test_balances_hide_empty_inactive_codes_and_show_fridge_units(ctx):  # noqa: F811
    live_id = _create_drink(ctx, "DUP-LIVE")
    old_empty_id = _create_drink(ctx, "DUP-OLD")
    old_stocked_id = _create_drink(ctx, "DUP-OLD-STOCKED")
    _seed_stock(ctx.client, old_stocked_id, 2)
    ctx.session.execute(
        text(
            "UPDATE products SET is_active = false, "
            "name = (SELECT name FROM products WHERE id = :live) "
            "WHERE id IN (:old, :stocked)"
        ),
        {"live": live_id, "old": old_empty_id, "stocked": old_stocked_id},
    )
    fridge_id = _create_fridge(ctx.client, f"{TAG}dup-fridge")
    ctx.session.execute(
        text(
            "INSERT INTO fridge_stock "
            "(fridge_id, product_code, product_id, units, expiry_dates, taken_at) "
            "SELECT :fridge, code, id, 6, '{}', :taken_at FROM products WHERE id = :product"
        ),
        {"fridge": fridge_id, "product": live_id, "taken_at": utcnow()},
    )

    default_rows = ctx.client.get(BALANCES_URL, params={"search": f"{TAG}DUP"}).json()["items"]
    all_rows = ctx.client.get(
        BALANCES_URL,
        params={"search": f"{TAG}DUP", "include_inactive": True},
    ).json()["items"]
    locations = ctx.client.get(f"{PREFIX}/stock/products/{old_empty_id}/fridges").json()

    visible = {row["product_id"]: (row["fridge_units"], row["is_active"]) for row in default_rows}
    assert visible == {live_id: (6, True), old_stocked_id: (0, False)}
    assert {row["product_id"] for row in all_rows} == {live_id, old_empty_id, old_stocked_id}
    assert locations["is_active"] is False
    assert locations["same_name_products"][0] == {
        "product_id": live_id,
        "product_code": f"{TAG}DUP-LIVE",
        "is_active": True,
        "fridge_units": 6,
    }


def test_new_adjustment_is_first_in_history(ctx):  # noqa: F811
    product_id = _create_drink(ctx, "MOV-2")
    _seed_stock(ctx.client, product_id, 8)
    ctx.client.post(
        f"{PREFIX}/stock/adjustments",
        json={"product_id": product_id, "qty": -3, "reason": f"{TAG}count"},
    )

    newest = ctx.client.get(MOVEMENTS_URL, params={"product_id": product_id}).json()["items"][0]

    assert newest["qty"] == -3
    assert newest["reason"] == f"{TAG}count"
