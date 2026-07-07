"""Integration tests for the operations routers against the live Railway DB.

Non-destructive by construction: every test runs inside a single outer
transaction bound to one connection, with the request ``Session`` joined in
``create_savepoint`` mode. Service-level ``commit()`` calls only release
savepoints; the outer transaction is rolled back on teardown, so nothing —
including append-only ``stock_movements`` rows — is ever persisted. Names use a
``ZZTEST-`` prefix as a second line of defence.
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

PREFIX = "/api/v1"
TAG = "ZZTEST-"

# A Wednesday (ISO weekday 3) used as the anchor delivery date.
DELIVERY_DATE = datetime.date(2026, 6, 17)
DELIVERY_WEEKDAY = DELIVERY_DATE.isoweekday()


@pytest.fixture()
def ctx():
    connection = engine.connect()
    outer = connection.begin()
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
        app.dependency_overrides.clear()
        session.close()
        outer.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# Seeding helpers (all within the rolled-back transaction)
# ---------------------------------------------------------------------------


def _category_ids(session: Session) -> dict[str, int]:
    rows = session.execute(text("SELECT id, name FROM categories")).all()
    normal = next(r.id for r in rows if "drink" not in r.name.lower() and "snack" not in r.name.lower())
    drinks = next(r.id for r in rows if "drink" in r.name.lower())
    return {"normal": normal, "drinks": drinks}


def _create_supplier(client: TestClient, name: str) -> int:
    resp = client.post(f"{PREFIX}/suppliers", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_product(
    client: TestClient, *, code: str, category_id: int, supplier_id: int | None = None,
    purchase="1.00", sales="2.12", vat="0.06",
) -> int:
    resp = client.post(
        f"{PREFIX}/products",
        json={
            "code": code,
            "name": f"{TAG}{code}",
            "category_id": category_id,
            "supplier_id": supplier_id,
            "purchase_price": purchase,
            "sales_price": sales,
            "vat_rate": vat,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_fridge(client: TestClient, husky_id: str) -> int:
    resp = client.post(
        f"{PREFIX}/fridges",
        json={"husky_id": husky_id, "friendly_name": f"{TAG}{husky_id}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_sales(session: Session, *, fridge_id: int, product_id: int, days: int) -> None:
    """One sale per day for ``days`` consecutive days ending the day before delivery."""
    for offset in range(1, days + 1):
        day = DELIVERY_DATE - datetime.timedelta(days=offset)
        sold_at = datetime.datetime(day.year, day.month, day.day, 12, tzinfo=datetime.timezone.utc)
        session.execute(
            text(
                "INSERT INTO sales_events (husky_ref, fridge_id, product_id, sold_at, "
                "unit_price, is_refunded) VALUES (:ref, :f, :p, :ts, :price, false)"
            ),
            {
                "ref": f"{TAG}sale-{product_id}-{offset}",
                "f": fridge_id,
                "p": product_id,
                "ts": sold_at,
                # sales_events.unit_price is BIGINT cents (migration 0002).
                "price": 212,
            },
        )
    session.flush()


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------


def test_categories_list(ctx):
    resp = ctx.client.get(f"{PREFIX}/categories")
    assert resp.status_code == 200
    # The seeded fixed category set is present (>= the canonical 10).
    assert len(resp.json()) >= 10


def test_supplier_crud_and_error_envelope(ctx):
    sid = _create_supplier(ctx.client, f"{TAG}Sup")
    assert ctx.client.get(f"{PREFIX}/suppliers/{sid}").json()["name"] == f"{TAG}Sup"

    upd = ctx.client.put(f"{PREFIX}/suppliers/{sid}", json={"email": "x@y.z"})
    assert upd.status_code == 200 and upd.json()["email"] == "x@y.z"

    listing = ctx.client.get(f"{PREFIX}/suppliers", params={"limit": 5})
    body = listing.json()
    assert set(body) == {"items", "total", "limit", "offset"} and body["limit"] == 5

    # Duplicate name -> 409 with error envelope.
    dup = ctx.client.post(f"{PREFIX}/suppliers", json={"name": f"{TAG}Sup"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"

    assert ctx.client.delete(f"{PREFIX}/suppliers/{sid}").status_code == 204

    missing = ctx.client.get(f"{PREFIX}/suppliers/999999999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_product_fridge_prices(ctx):
    cats = _category_ids(ctx.session)
    pid = _create_product(ctx.client, code=f"{TAG}P1", category_id=cats["normal"])
    fid = _create_fridge(ctx.client, f"{TAG}fr1")

    put = ctx.client.put(
        f"{PREFIX}/products/{pid}/fridge-prices",
        json={"items": [{"fridge_id": fid, "sales_price": "3.50"}]},
    )
    assert put.status_code == 200, put.text
    prices = ctx.client.get(f"{PREFIX}/products/{pid}/fridge-prices").json()
    assert prices[0]["sales_price"] == "3.50"


def test_client_fees_and_interventions(ctx):
    created = ctx.client.post(f"{PREFIX}/clients", json={"name": f"{TAG}Client"})
    cid = created.json()["id"]

    fee = ctx.client.post(
        f"{PREFIX}/clients/{cid}/fees",
        json={"yearly_fee": "1200.00", "contract_start": "2026-01-01"},
    )
    assert fee.status_code == 201 and fee.json()["yearly_fee"] == "1200.00"

    # Fridge tied to the client, then an intervention on it.
    fr = ctx.client.post(
        f"{PREFIX}/fridges",
        json={"husky_id": f"{TAG}frC", "friendly_name": f"{TAG}frC", "client_id": cid},
    )
    fid = fr.json()["id"]
    iv = ctx.client.post(
        f"{PREFIX}/clients/{cid}/interventions",
        json={
            "fridge_id": fid,
            "intervention_type": "cleaning",
            "occurred_at": "2026-06-01T09:00:00+00:00",
        },
    )
    assert iv.status_code == 201
    assert len(ctx.client.get(f"{PREFIX}/clients/{cid}/interventions").json()) == 1


def test_fridge_delivery_config(ctx):
    fid = _create_fridge(ctx.client, f"{TAG}frDC")
    put = ctx.client.put(
        f"{PREFIX}/fridges/{fid}/delivery-config",
        json={"items": [{"weekday": 3, "min_daily_qty": 0, "days_to_fill": 3}]},
    )
    assert put.status_code == 200
    cfg = ctx.client.get(f"{PREFIX}/fridges/{fid}/delivery-config").json()
    assert cfg == [{"weekday": 3, "min_daily_qty": 0, "days_to_fill": 3}]


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------


def test_menu_lifecycle(ctx):
    cats = _category_ids(ctx.session)
    pid = _create_product(ctx.client, code=f"{TAG}Pm", category_id=cats["normal"])
    fid = _create_fridge(ctx.client, f"{TAG}frM")

    menu = ctx.client.post(f"{PREFIX}/menus", params={"year": 2026, "week": 25}).json()
    assert menu["status"] == "draft"

    assert ctx.client.put(
        f"{PREFIX}/menus/{menu['id']}/products", json={"product_ids": [pid]}
    ).status_code == 200

    # Targets + caps are fridge-scoped.
    tgt = ctx.client.put(
        f"{PREFIX}/menus/product-targets",
        params={"fridge_id": fid},
        json={"items": [{"product_id": pid, "target_qty": 5}]},
    )
    assert tgt.status_code == 200 and tgt.json()[0]["target_qty"] == 5

    cap = ctx.client.put(
        f"{PREFIX}/menus/menu-caps",
        params={"fridge_id": fid},
        json={"items": [{"product_id": pid, "max_qty": 10}]},
    )
    assert cap.status_code == 200 and cap.json()[0]["max_qty"] == 10

    # Copy into a second menu.
    menu2 = ctx.client.post(f"{PREFIX}/menus", params={"year": 2026, "week": 26}).json()
    copy = ctx.client.post(f"{PREFIX}/menus/{menu2['id']}/copy-from/{menu['id']}")
    assert copy.status_code == 200 and copy.json()["copied_from_id"] == menu["id"]


# ---------------------------------------------------------------------------
# Forecast + scoring + allocation
# ---------------------------------------------------------------------------


def test_forecast_scoring_allocation_end_to_end(ctx):
    cats = _category_ids(ctx.session)
    sid = _create_supplier(ctx.client, f"{TAG}SupF")
    normal_pid = _create_product(
        ctx.client, code=f"{TAG}Pf", category_id=cats["normal"], supplier_id=sid
    )
    drink_pid = _create_product(ctx.client, code=f"{TAG}Pd", category_id=cats["drinks"])
    fid = _create_fridge(ctx.client, f"{TAG}frF")

    ctx.client.put(
        f"{PREFIX}/fridges/{fid}/delivery-config",
        json={"items": [{"weekday": DELIVERY_WEEKDAY, "min_daily_qty": 0, "days_to_fill": 3}]},
    )
    # 21 sales across 21 distinct lookback days -> avg 1/day * 3 days_to_fill = 3.00.
    _seed_sales(ctx.session, fridge_id=fid, product_id=normal_pid, days=21)

    run = ctx.client.post(
        f"{PREFIX}/forecasts/run", json={"delivery_date": DELIVERY_DATE.isoformat()}
    )
    assert run.status_code == 200, run.text
    run_body = run.json()
    normal_cell = next(
        r for r in run_body["results"] if r["category_id"] == cats["normal"]
    )
    assert normal_cell["forecast_qty"] == "3.00"
    assert normal_cell["valid_days"] == 21
    assert normal_cell["holiday_days"] == 0

    # GET latest returns the same run.
    latest = ctx.client.get(
        f"{PREFIX}/forecasts/latest", params={"delivery_date": DELIVERY_DATE.isoformat()}
    )
    assert latest.json()["run_id"] == run_body["run_id"]

    # --- Scoring: added=10, sold=21, margin=0.5, review=0.6 ---
    for i in range(10):
        ctx.session.execute(
            text(
                "INSERT INTO restock_events (husky_ref, fridge_id, product_id, action, "
                "tag_status, occurred_at) VALUES (:ref, :f, :p, 'added', 'valid', :ts)"
            ),
            {
                "ref": f"{TAG}add-{i}",
                "f": fid,
                "p": normal_pid,
                "ts": datetime.datetime(2026, 6, 1, 10, tzinfo=datetime.timezone.utc),
            },
        )
    for i, rating in enumerate([1, 1, 1, 1, 0]):
        ctx.session.execute(
            text(
                "INSERT INTO product_reviews (husky_ref, product_id, fridge_id, rating, "
                "reviewed_at) VALUES (:ref, :p, :f, :r, :ts)"
            ),
            {
                "ref": f"{TAG}rev-{i}",
                "p": normal_pid,
                "f": fid,
                "r": rating,
                "ts": datetime.datetime(2026, 6, 2, 10, tzinfo=datetime.timezone.utc),
            },
        )
    ctx.session.flush()

    rec = ctx.client.post(
        f"{PREFIX}/forecasts/scores/recompute", json={"as_of": DELIVERY_DATE.isoformat()}
    )
    assert rec.status_code == 200 and rec.json()["products_scored"] >= 1

    scores = ctx.client.get(
        f"{PREFIX}/forecasts/scores",
        params={"product_id": normal_pid, "period_end": DELIVERY_DATE.isoformat()},
    ).json()["items"]
    score = next(s for s in scores if s["product_id"] == normal_pid)
    # 0.62*2.1 + 0.33*0.5 + 0.05*0.6 = 1.4970
    assert score["final_score"] == "1.4970"
    assert score["pct_sold"] == "2.1000"
    assert score["margin_score"] == "0.5000"

    # --- Allocation: menu with both products; normal -> 3, drink -> target 5 ---
    menu = ctx.client.post(f"{PREFIX}/menus", params={"year": 2026, "week": 25}).json()
    ctx.client.put(
        f"{PREFIX}/menus/{menu['id']}/products",
        json={"product_ids": [normal_pid, drink_pid]},
    )
    ctx.client.put(
        f"{PREFIX}/menus/product-targets",
        params={"fridge_id": fid},
        json={"items": [{"product_id": drink_pid, "target_qty": 5}]},
    )
    alloc = ctx.client.post(
        f"{PREFIX}/menus/{menu['id']}/allocate",
        params={"forecast_run_id": run_body["run_id"]},
    )
    assert alloc.status_code == 200, alloc.text
    lines = {(l["product_id"], l["source"]): l["qty"] for l in alloc.json()["lines"]}
    assert lines[(normal_pid, "forecast")] == 3
    assert lines[(drink_pid, "target_replenish")] == 5


# ---------------------------------------------------------------------------
# Dispatch confirm transaction + stock
# ---------------------------------------------------------------------------


def _seed_stock(client: TestClient, product_id: int, qty: int) -> None:
    resp = client.post(
        f"{PREFIX}/stock/adjustments",
        json={"product_id": product_id, "qty": qty, "reason": f"{TAG}seed"},
    )
    assert resp.status_code == 201, resp.text


def test_dispatch_confirm_happy_and_idempotent(ctx):
    cats = _category_ids(ctx.session)
    pid = _create_product(ctx.client, code=f"{TAG}Pdsp", category_id=cats["normal"])
    fid = _create_fridge(ctx.client, f"{TAG}frDsp")
    _seed_stock(ctx.client, pid, 10)

    disp = ctx.client.post(
        f"{PREFIX}/dispatches", json={"delivery_date": DELIVERY_DATE.isoformat()}
    ).json()
    ctx.client.put(
        f"{PREFIX}/dispatches/{disp['id']}/lines",
        json={"lines": [{"fridge_id": fid, "product_id": pid, "qty": 4}]},
    )

    matrix = ctx.client.get(f"{PREFIX}/dispatches/{disp['id']}/matrix").json()
    assert matrix["cells"][0]["qty"] == 4

    # Past date without force -> 409.
    confirm = ctx.client.post(f"{PREFIX}/dispatches/{disp['id']}/confirm", json={"force": False})
    assert confirm.status_code == 409
    assert confirm.json()["error"]["code"] == "past_date_requires_force"

    forced = ctx.client.post(f"{PREFIX}/dispatches/{disp['id']}/confirm", json={"force": True})
    assert forced.status_code == 200, forced.text
    assert forced.json()["status"] == "dispatched"
    assert forced.json()["movements_created"] == 1

    # Balance dropped from 10 to 6.
    bal = ctx.client.get(f"{PREFIX}/stock/balances", params={"search": f"{TAG}Pdsp"}).json()
    assert bal["items"][0]["physical_qty"] == 6

    # Idempotent re-confirm.
    again = ctx.client.post(f"{PREFIX}/dispatches/{disp['id']}/confirm", json={"force": True})
    assert again.status_code == 200 and again.json()["status"] == "dispatched"


def test_dispatch_confirm_stock_blocked(ctx):
    cats = _category_ids(ctx.session)
    pid = _create_product(ctx.client, code=f"{TAG}Pblk", category_id=cats["normal"])
    fid = _create_fridge(ctx.client, f"{TAG}frBlk")

    disp = ctx.client.post(
        f"{PREFIX}/dispatches", json={"delivery_date": datetime.date(2026, 6, 24).isoformat()}
    ).json()
    ctx.client.put(
        f"{PREFIX}/dispatches/{disp['id']}/lines",
        json={"lines": [{"fridge_id": fid, "product_id": pid, "qty": 5}]},
    )
    blocked = ctx.client.post(f"{PREFIX}/dispatches/{disp['id']}/confirm", json={"force": True})
    assert blocked.status_code == 409, blocked.text
    body = blocked.json()["error"]
    assert body["code"] == "stock_blocked"
    assert body["details"][0]["product_id"] == pid


def test_stock_adjustment_validation_and_movements(ctx):
    cats = _category_ids(ctx.session)
    pid = _create_product(ctx.client, code=f"{TAG}Padj", category_id=cats["normal"])

    # Blank reason -> 422.
    bad = ctx.client.post(
        f"{PREFIX}/stock/adjustments",
        json={"product_id": pid, "qty": 5, "reason": "   "},
    )
    assert bad.status_code == 422

    # Zero qty -> 422.
    zero = ctx.client.post(
        f"{PREFIX}/stock/adjustments",
        json={"product_id": pid, "qty": 0, "reason": f"{TAG}x"},
    )
    assert zero.status_code == 422

    _seed_stock(ctx.client, pid, 7)

    # Negative adjustment below zero -> 409 stock_blocked.
    neg = ctx.client.post(
        f"{PREFIX}/stock/adjustments",
        json={"product_id": pid, "qty": -100, "reason": f"{TAG}drain"},
    )
    assert neg.status_code == 409 and neg.json()["error"]["code"] == "stock_blocked"

    moves = ctx.client.get(f"{PREFIX}/stock/movements", params={"product_id": pid}).json()
    assert moves["items"][0]["movement_type"] == "adjustment"
    assert moves["items"][0]["qty"] == 7
