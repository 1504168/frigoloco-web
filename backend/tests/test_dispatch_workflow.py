"""Dispatch page workflow: the saved dispatch lists every fridge delivered that day.

Reuses the rolled-back ``ctx`` fixture and seeding helpers of
``test_workflow_pipeline`` so nothing is persisted.
"""

from __future__ import annotations

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

DISPATCH_KEY = {"year": YEAR, "week": WEEK, "day_name": DAY_NAME}


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
