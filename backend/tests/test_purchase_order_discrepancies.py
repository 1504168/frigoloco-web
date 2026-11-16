"""Purchase orders: close short, discrepancy log, activity history, menu order plan.

Reuses the rolled-back-transaction fixtures of test_finance_routers.
"""

from __future__ import annotations

from sqlalchemy import text

from app.models.planning import MenuLine, WeeklyMenu
from app.services.orders_service import compute_to_order_qty
from tests import test_finance_routers as finance_tests
from tests.test_finance_routers import Seed, _po_payload, _stock_balance

# Re-exposed so pytest finds the shared rolled-back-transaction fixtures in this module.
db_session = finance_tests.db_session
client = finance_tests.client
seed = finance_tests.seed

PLAN_YEAR = 2099
PLAN_WEEK = 10


def _receive(client, po: dict, qty: int, acknowledge: bool = False) -> dict:
    response = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={
            "received": [{"po_line_id": po["lines"][0]["id"], "qty_received": qty}],
            "acknowledge_over_receipt": acknowledge,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _view_on_order(db_session, product_id: int) -> int:
    return db_session.execute(
        text("SELECT on_order_qty FROM v_stock_balances WHERE product_id = :id"),
        {"id": product_id},
    ).scalar_one()


def test_to_order_qty_never_below_zero() -> None:
    assert compute_to_order_qty(need_qty=10, in_stock_qty=3, on_order_qty=2) == 5
    assert compute_to_order_qty(need_qty=4, in_stock_qty=3, on_order_qty=2) == 0


def test_close_short_logs_shortfall_and_drops_on_order(client, seed, db_session) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=10)).json()
    _receive(client, po, 7)
    assert _view_on_order(db_session, seed.product_id) == 3

    line_id = po["lines"][0]["id"]
    closed = client.post(
        f"/api/v1/purchase-orders/{po['id']}/close-short",
        json={"lines": [{"po_line_id": line_id, "reason": "damaged", "comment": " 3 broken "}]},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed_short"
    assert _view_on_order(db_session, seed.product_id) == 0
    assert _stock_balance(db_session, seed.product_id) == 7

    log = client.get(
        "/api/v1/purchase-orders/discrepancies",
        params={"supplier_id": seed.supplier_id},
    ).json()
    assert log["total"] == 1
    shortfall = log["items"][0]
    assert shortfall["kind"] == "short"
    assert shortfall["qty_ordered"] == 10
    assert shortfall["qty_received"] == 7
    assert shortfall["qty_difference"] == 3
    assert shortfall["reason"] == "damaged"
    assert shortfall["comment"] == "3 broken"
    assert shortfall["order_no"] == po["order_no"]

    again = client.post(f"/api/v1/purchase-orders/{po['id']}/close-short", json={"lines": []})
    assert again.status_code == 409


def test_close_short_rejects_line_of_other_order(client, seed) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=10)).json()
    response = client.post(
        f"/api/v1/purchase-orders/{po['id']}/close-short",
        json={"lines": [{"po_line_id": -1}]},
    )
    assert response.status_code == 422


def test_over_receipt_is_logged(client, seed) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=5)).json()
    _receive(client, po, 7, acknowledge=True)

    log = client.get(
        "/api/v1/purchase-orders/discrepancies",
        params={"supplier_id": seed.supplier_id, "kind": "over"},
    ).json()
    assert log["total"] == 1
    assert log["items"][0]["qty_received"] == 7
    assert log["items"][0]["qty_difference"] == 2


def test_history_lists_every_action_newest_first(client, seed) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=10)).json()
    client.patch(f"/api/v1/purchase-orders/{po['id']}", json={"comment": "ZZTEST edited"})
    _receive(client, po, 4)
    client.post(f"/api/v1/purchase-orders/{po['id']}/close-short", json={"lines": []})
    client.post(f"/api/v1/purchase-orders/{po['id']}/cancel")

    response = client.get(f"/api/v1/purchase-orders/{po['id']}/history")
    assert response.status_code == 200, response.text
    events = response.json()
    assert [event["action"] for event in events] == [
        "cancelled",
        "closed_short",
        "received",
        "edited",
        "created",
    ]
    cancelled, closed_short, received, edited, created = events
    assert cancelled["lines"][0]["detail"] == "4 units taken back out of warehouse stock"
    assert closed_short["lines"][0]["detail"] == "ordered 10, received 4, short 6"
    assert received["lines"][0]["detail"] == "received 4"
    assert edited["lines"][0]["detail"] == "ZZTEST -> ZZTEST edited"
    assert created["lines"][0]["detail"] == "ordered 10"
    assert created["user_name"] is not None


def test_menu_order_plan_per_supplier(client, seed: Seed, db_session) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=3)).json()
    _receive(client, po, 2)
    menu = WeeklyMenu(year=PLAN_YEAR, iso_week=PLAN_WEEK, day_name="Tuesday")
    db_session.add(menu)
    db_session.flush()
    db_session.add(
        MenuLine(
            menu_id=menu.id,
            fridge_id=seed.fridge_id,
            product_id=seed.product_id,
            category_id=seed.category_id,
            qty=10,
        )
    )
    db_session.flush()

    response = client.get(
        "/api/v1/purchase-orders/menu-order-plan",
        params={"year": PLAN_YEAR, "week": PLAN_WEEK, "day_names": ["Tuesday", "Wednesday"]},
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["days_without_menu"] == ["Wednesday"]
    assert plan["expected_delivery_date"] == "2099-03-03"
    supplier_card = next(
        card for card in plan["suppliers"] if card["supplier_id"] == seed.supplier_id
    )
    plan_line = supplier_card["lines"][0]
    assert plan_line["need_qty"] == 10
    assert plan_line["in_stock_qty"] == 2
    assert plan_line["on_order_qty"] == 1
    assert plan_line["to_order_qty"] == 7
