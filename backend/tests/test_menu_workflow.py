"""Menu page workflow: zero-qty products, delivery fridge rows, effective status.

Reuses the rolled-back ``ctx`` fixture and seeding helpers of
``test_workflow_pipeline`` so nothing is persisted.
"""

from __future__ import annotations

from sqlalchemy import text

from app.services.menu_service import _active_products_by_category
from tests.test_workflow_pipeline import (
    DAY_NAME,
    DELIVERY_WEEKDAY,
    PREFIX,
    TAG,
    WEEK,
    YEAR,
    _create_fridge,
    _create_product,
    _create_supplier,
    _normal_category_id,
    ctx,  # noqa: F401 - pytest fixture
)

MENU_KEY = {"year": YEAR, "week": WEEK, "day_name": DAY_NAME}


def test_menu_save_keeps_products_without_quantities(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    category_id = _normal_category_id(session)
    supplier_id = _create_supplier(client, f"{TAG}ZeroSup")
    ordered_product = _create_product(
        client,
        code=f"{TAG}Z1",
        category_id=category_id,
        supplier_id=supplier_id,
    )
    empty_product = _create_product(
        client,
        code=f"{TAG}Z2",
        category_id=category_id,
        supplier_id=supplier_id,
    )
    first_fridge = _create_fridge(client, f"{TAG}zfr1")
    second_fridge = _create_fridge(client, f"{TAG}zfr2")

    save = client.post(
        f"{PREFIX}/menus/save",
        json={
            **MENU_KEY,
            "lines": [
                {"fridge_id": first_fridge, "product_id": ordered_product, "qty": 4},
                {"fridge_id": second_fridge, "product_id": ordered_product, "qty": 0},
                {"fridge_id": first_fridge, "product_id": empty_product, "qty": 0},
            ],
        },
    )
    assert save.status_code == 200, save.text

    saved = client.get(f"{PREFIX}/menus/saved", params=MENU_KEY).json()
    saved_product_ids = {product["product_id"] for product in saved["products"]}
    assert {ordered_product, empty_product} <= saved_product_ids
    stored_cells = {
        (cell["fridge_id"], cell["product_id"]): cell["qty"] for cell in saved["cells"]
    }
    assert stored_cells == {
        (first_fridge, ordered_product): 4,
        (first_fridge, empty_product): 0,
    }


def test_menu_fridge_rows_come_from_delivery_config(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    category_id = _normal_category_id(session)
    supplier_id = _create_supplier(client, f"{TAG}RowSup")
    product_id = _create_product(
        client,
        code=f"{TAG}R1",
        category_id=category_id,
        supplier_id=supplier_id,
    )
    menu_fridge = _create_fridge(client, f"{TAG}rfr1")
    delivered_fridge = _create_fridge(client, f"{TAG}rfr2")
    cancelled_fridge = _create_fridge(client, f"{TAG}rfr3")
    undelivered_fridge = _create_fridge(client, f"{TAG}rfr4")
    for fridge_id in (delivered_fridge, cancelled_fridge):
        config = client.put(
            f"{PREFIX}/fridges/{fridge_id}/delivery-config",
            json={"items": [{"weekday": DELIVERY_WEEKDAY, "min_daily_qty": 0}]},
        )
        assert config.status_code == 200, config.text
    session.execute(
        text("UPDATE fridges SET local_status = 'cancelled' WHERE id = :id"),
        {"id": cancelled_fridge},
    )
    session.flush()

    save = client.post(
        f"{PREFIX}/menus/save",
        json={
            **MENU_KEY,
            "lines": [{"fridge_id": menu_fridge, "product_id": product_id, "qty": 2}],
        },
    )
    assert save.status_code == 200, save.text

    saved = client.get(f"{PREFIX}/menus/saved", params=MENU_KEY).json()
    fridge_ids = {fridge["fridge_id"] for fridge in saved["fridges"]}
    assert {menu_fridge, delivered_fridge} <= fridge_ids
    assert cancelled_fridge not in fridge_ids
    assert undelivered_fridge not in fridge_ids


def test_forecast_split_skips_products_disabled_locally(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    category_id = _normal_category_id(session)
    supplier_id = _create_supplier(client, f"{TAG}StatusSup")
    active_product = _create_product(
        client,
        code=f"{TAG}S1",
        category_id=category_id,
        supplier_id=supplier_id,
    )
    disabled_product = _create_product(
        client,
        code=f"{TAG}S2",
        category_id=category_id,
        supplier_id=supplier_id,
    )
    session.execute(
        text("UPDATE products SET local_status = 'inactive' WHERE id = :id"),
        {"id": disabled_product},
    )
    session.flush()

    products_by_category = _active_products_by_category(session)

    assert active_product in products_by_category[category_id]
    assert disabled_product not in products_by_category[category_id]


def test_menu_stock_balances_lists_every_product(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    category_id = _normal_category_id(session)
    supplier_id = _create_supplier(client, f"{TAG}StockSup")
    product_id = _create_product(
        client,
        code=f"{TAG}B1",
        category_id=category_id,
        supplier_id=supplier_id,
    )
    opening = client.post(
        f"{PREFIX}/stock/opening-stock",
        json={"product_id": product_id, "qty": 7, "reason": f"{TAG}take"},
    )
    assert opening.status_code == 201, opening.text

    balances = client.get(f"{PREFIX}/menus/stock-balances")
    assert balances.status_code == 200, balances.text
    balance = next(item for item in balances.json() if item["product_id"] == product_id)
    assert balance == {"product_id": product_id, "in_stock_qty": 7, "on_order_qty": 0}


def test_blank_menu_lists_delivery_fridges(ctx):  # noqa: F811
    client = ctx.client
    delivered_fridge = _create_fridge(client, f"{TAG}bfr1")
    config = client.put(
        f"{PREFIX}/fridges/{delivered_fridge}/delivery-config",
        json={"items": [{"weekday": DELIVERY_WEEKDAY, "min_daily_qty": 0}]},
    )
    assert config.status_code == 200, config.text

    blank = client.get(f"{PREFIX}/menus/blank", params=MENU_KEY)

    assert blank.status_code == 200, blank.text
    body = blank.json()
    assert body["menu_id"] is None
    assert body["products"] == [] and body["cells"] == []
    assert delivered_fridge in {fridge["fridge_id"] for fridge in body["fridges"]}
