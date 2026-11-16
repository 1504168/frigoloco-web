"""Dispatch page workflow: the saved dispatch lists every fridge delivered that day.

Reuses the rolled-back ``ctx`` fixture and seeding helpers of
``test_workflow_pipeline`` so nothing is persisted.
"""

from __future__ import annotations

import datetime

from fastapi.testclient import TestClient

from tests.test_workflow_pipeline import (
    DAY_NAME,
    DELIVERY_DATE,
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

DISPATCH_KEY = {"year": YEAR, "week": WEEK, "day_name": DAY_NAME}
ONE_DAY = datetime.timedelta(days=1)


def test_saved_dispatch_matrix_lists_delivery_fridges(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    product_id = _create_product(
        client,
        code=f"{TAG}DM1",
        category_id=_normal_category_id(session),
        supplier_id=_create_supplier(client, f"{TAG}DispSup"),
    )
    dispatched_fridge = _create_fridge(client, f"{TAG}dfr1")
    delivered_fridge = _create_fridge(client, f"{TAG}dfr2")
    undelivered_fridge = _create_fridge(client, f"{TAG}dfr3")
    config = client.put(
        f"{PREFIX}/fridges/{delivered_fridge}/delivery-config",
        json={"items": [{"weekday": DELIVERY_WEEKDAY, "min_daily_qty": 0}]},
    )
    assert config.status_code == 200, config.text

    save = client.post(
        f"{PREFIX}/dispatches/save",
        json={
            **DISPATCH_KEY,
            "lines": [{"fridge_id": dispatched_fridge, "product_id": product_id, "qty": 3}],
        },
    )
    assert save.status_code == 200, save.text

    matrix = client.get(f"{PREFIX}/dispatches/{save.json()['id']}/matrix").json()
    fridge_ids = {fridge["fridge_id"] for fridge in matrix["fridges"]}
    assert {dispatched_fridge, delivered_fridge} <= fridge_ids
    assert undelivered_fridge not in fridge_ids
    assert matrix["cells"] == [
        {"fridge_id": dispatched_fridge, "product_id": product_id, "qty": 3},
    ]


def test_fit_to_stock_counts_only_pending_orders_due_by_the_delivery(ctx):  # noqa: F811
    client, session = ctx.client, ctx.session
    supplier_id = _create_supplier(client, f"{TAG}FitSup")
    product_id = _create_product(
        client,
        code=f"{TAG}FIT",
        category_id=_normal_category_id(session),
        supplier_id=supplier_id,
    )
    opening = client.post(
        f"{PREFIX}/stock/opening-stock",
        json={"product_id": product_id, "qty": 2, "reason": f"{TAG}fit test"},
    )
    assert opening.status_code == 201, opening.text
    _create_purchase_order(client, supplier_id, product_id, qty=3, due=DELIVERY_DATE)
    _create_purchase_order(client, supplier_id, product_id, qty=5, due=DELIVERY_DATE + ONE_DAY)
    cancelled_po = _create_purchase_order(
        client, supplier_id, product_id, qty=4, due=DELIVERY_DATE - ONE_DAY
    )
    cancel = client.post(f"{PREFIX}/purchase-orders/{cancelled_po}/cancel")
    assert cancel.status_code == 200, cancel.text
    fridge_one = _create_fridge(client, f"{TAG}fit1")
    fridge_two = _create_fridge(client, f"{TAG}fit2")
    planned_lines = [
        {"fridge_id": fridge_one, "product_id": product_id, "qty": 8},
        {"fridge_id": fridge_two, "product_id": product_id, "qty": 2},
    ]

    shelf_only = client.post(f"{PREFIX}/dispatches/fit-to-stock", json={"lines": planned_lines})
    with_orders = client.post(
        f"{PREFIX}/dispatches/fit-to-stock",
        json={"lines": planned_lines, "include_orders_due_by": DELIVERY_DATE.isoformat()},
    )

    assert shelf_only.status_code == 200, shelf_only.text
    assert shelf_only.json()["cuts"] == [
        {"product_id": product_id, "requested": 10, "in_stock": 2, "cut": 8, "on_order": 0}
    ]
    assert shelf_only.json()["order_uses"] == []
    assert with_orders.status_code == 200, with_orders.text
    assert [line["qty"] for line in with_orders.json()["lines"]] == [4, 1]
    assert with_orders.json()["cuts"] == [
        {"product_id": product_id, "requested": 10, "in_stock": 5, "cut": 5, "on_order": 3}
    ]
    assert with_orders.json()["order_uses"] == [
        {"product_id": product_id, "units_from_orders": 3}
    ]


def _create_purchase_order(
    client: TestClient,
    supplier_id: int,
    product_id: int,
    qty: int,
    due: datetime.date,
) -> int:
    response = client.post(
        f"{PREFIX}/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "order_date": datetime.date.today().isoformat(),
            "expected_delivery_date": due.isoformat(),
            "lines": [
                {"product_id": product_id, "qty": qty, "unit_price": "1.00", "vat_rate": "0.06"}
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]
