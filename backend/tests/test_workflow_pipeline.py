"""End-to-end (iso_year, week_no, day_name) workflow pipeline test (D2).

Exercises the full Forecast -> Menu -> Dispatch -> PO pipeline against the live
Railway DB on synthetic week 2027-W2 (Wednesday, delivery_date 2027-01-13;
partitions exist through 2027-12). Like ``test_ops_routers``, everything runs
inside one outer transaction rolled back on teardown - nothing (including
append-only ``stock_movements`` / ``menu_lines`` rows) is ever persisted. Names
use a ``ZZWF-`` prefix as a second line of defence.

Pipeline covered:
  run forecast (compute, unsaved) -> save (409-on-exists then overwrite) ->
  load-saved -> import to menu -> edit + save (409 then overwrite) -> load-saved
  -> import to dispatch -> save PLANNED (stock UNCHANGED) -> create individual
  dispatch (stock REDUCED) -> draft PO from menu. Plus the opening-stock flow.
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
TAG = "ZZWF-"

YEAR, WEEK, DAY_NAME = 2027, 2, "Wednesday"
DELIVERY_DATE = datetime.date.fromisocalendar(YEAR, WEEK, 3)  # 2027-01-13
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


# --- seeding helpers (all inside the rolled-back transaction) ---------------


def _normal_category_id(session: Session) -> int:
    row = session.execute(
        text(
            "SELECT id FROM categories "
            "WHERE lower(name) NOT LIKE '%drink%' AND lower(name) NOT LIKE '%snack%' "
            "ORDER BY id LIMIT 1"
        )
    ).one()
    return row.id


def _create_supplier(client: TestClient, name: str) -> int:
    resp = client.post(f"{PREFIX}/suppliers", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_product(client: TestClient, *, code: str, category_id: int, supplier_id: int) -> int:
    resp = client.post(
        f"{PREFIX}/products",
        json={
            "code": code,
            "name": f"{TAG}{code}",
            "category_id": category_id,
            "supplier_id": supplier_id,
            "purchase_price": "1.00",
            "sales_price": "2.50",
            "vat_rate": "0.06",
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
    """One sale per day for ``days`` days ending the day before delivery."""
    for offset in range(1, days + 1):
        day = DELIVERY_DATE - datetime.timedelta(days=offset)
        sold_at = datetime.datetime(day.year, day.month, day.day, 12, tzinfo=datetime.timezone.utc)
        session.execute(
            text(
                "INSERT INTO sales_events (husky_ref, fridge_id, product_id, sold_at, "
                "unit_price, is_refunded) VALUES (:ref, :f, :p, :ts, 250, false)"
            ),
            {"ref": f"{TAG}sale-{product_id}-{offset}", "f": fridge_id, "p": product_id, "ts": sold_at},
        )
    session.flush()


def _seed_restock(
    session: Session,
    *,
    fridge_id: int,
    product_id: int,
    action: str,
    tag_status: str,
    count: int,
) -> None:
    """Insert ``count`` restock events on the day before delivery (in-window)."""
    day = DELIVERY_DATE - datetime.timedelta(days=1)  # inside the 21-day window
    occurred = datetime.datetime(day.year, day.month, day.day, 12, tzinfo=datetime.timezone.utc)
    for index in range(count):
        session.execute(
            text(
                "INSERT INTO restock_events (husky_ref, fridge_id, product_id, action, "
                "tag_status, occurred_at) VALUES (:ref, :f, :p, :a, :s, :ts)"
            ),
            {
                "ref": f"{TAG}rs-{action}-{tag_status}-{index}",
                "f": fridge_id,
                "p": product_id,
                "a": action,
                "s": tag_status,
                "ts": occurred,
            },
        )
    session.flush()


def test_forecast_actuals_added_sold_ratio(ctx):
    """GET /forecasts/actuals reports VALID-ADDED vs sold per fridge×category."""
    client, session = ctx.client, ctx.session
    cat = _normal_category_id(session)
    supplier_id = _create_supplier(client, f"{TAG}SupA")
    product_id = _create_product(client, code=f"{TAG}PA", category_id=cat, supplier_id=supplier_id)
    fridge_id = _create_fridge(client, f"{TAG}frA")
    client.put(
        f"{PREFIX}/fridges/{fridge_id}/delivery-config",
        json={"items": [{"weekday": DELIVERY_WEEKDAY, "min_daily_qty": 0, "days_to_fill": 3}]},
    )

    _seed_sales(session, fridge_id=fridge_id, product_id=product_id, days=21)  # 21 sold
    _seed_restock(session, fridge_id=fridge_id, product_id=product_id, action="added", tag_status="valid", count=10)
    # These must NOT count toward added_qty (removed, and non-valid tag status).
    _seed_restock(session, fridge_id=fridge_id, product_id=product_id, action="removed", tag_status="valid", count=4)
    _seed_restock(session, fridge_id=fridge_id, product_id=product_id, action="added", tag_status="unreliable", count=3)

    resp = client.get(
        f"{PREFIX}/forecasts/actuals",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["year"], body["week"], body["day_name"]) == (YEAR, WEEK, DAY_NAME)
    cell = next(
        c for c in body["cells"] if c["fridge_id"] == fridge_id and c["category_id"] == cat
    )
    assert cell["added_qty"] == 10   # only VALID ADDED
    assert cell["sold_qty"] == 21
    assert cell["ratio"] == "2.1000"  # 21 / 10


def _balance(client: TestClient, code: str) -> int:
    resp = client.get(f"{PREFIX}/stock/balances", params={"search": code})
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    return int(items[0]["physical_qty"]) if items else 0


# --- the pipeline -----------------------------------------------------------


def test_full_workflow_pipeline_2027_w2(ctx):
    client, session = ctx.client, ctx.session
    cat = _normal_category_id(session)
    supplier_id = _create_supplier(client, f"{TAG}Sup")
    product_id = _create_product(client, code=f"{TAG}P1", category_id=cat, supplier_id=supplier_id)
    fridge_id = _create_fridge(client, f"{TAG}fr1")

    client.put(
        f"{PREFIX}/fridges/{fridge_id}/delivery-config",
        json={"items": [{"weekday": DELIVERY_WEEKDAY, "min_daily_qty": 0, "days_to_fill": 3}]},
    )
    # 21 sales / 21 lookback days -> avg 1/day * days_to_fill 3 = 3.00 forecast.
    _seed_sales(session, fridge_id=fridge_id, product_id=product_id, days=21)

    # 1) run forecast: computes, is_saved=false.
    run = client.post(f"{PREFIX}/forecasts/run", json={"delivery_date": DELIVERY_DATE.isoformat()})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["is_saved"] is False
    assert body["model"] == "moving_average_3w"
    assert (body["iso_year"], body["week_no"], body["day_name"]) == (YEAR, WEEK, DAY_NAME)
    normal_cell = next(r for r in body["results"] if r["category_id"] == cat)
    assert normal_cell["forecast_qty"] == "3.00"

    # 2) save forecast (persist keyed); overwrite-confirm.
    save_body = {"year": YEAR, "week": WEEK, "day_name": DAY_NAME}
    saved = client.post(f"{PREFIX}/forecasts/save", json=save_body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_saved"] is True

    dup = client.post(f"{PREFIX}/forecasts/save", json=save_body)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "exists"

    overwritten = client.post(f"{PREFIX}/forecasts/save", json={**save_body, "overwrite": True})
    assert overwritten.status_code == 200, overwritten.text

    # 3) load-saved.
    loaded = client.get(
        f"{PREFIX}/forecasts/saved", params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME}
    )
    assert loaded.status_code == 200 and loaded.json()["is_saved"] is True

    # 4) import to menu (compute preview from saved forecast).
    imp = client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME},
    )
    assert imp.status_code == 200, imp.text
    assert len(imp.json()["cells"]) >= 1  # forecast allocated across category products

    # 5) edit + save menu with an explicit, deterministic grid.
    menu_save = {
        "year": YEAR,
        "week": WEEK,
        "day_name": DAY_NAME,
        "lines": [{"fridge_id": fridge_id, "product_id": product_id, "qty": 5}],
    }
    m1 = client.post(f"{PREFIX}/menus/save", json=menu_save)
    assert m1.status_code == 200, m1.text
    assert m1.json()["menu_id"] is not None

    m_dup = client.post(f"{PREFIX}/menus/save", json=menu_save)
    assert m_dup.status_code == 409 and m_dup.json()["error"]["code"] == "exists"

    menu_save["lines"][0]["qty"] = 6  # modify
    m2 = client.post(f"{PREFIX}/menus/save", json={**menu_save, "overwrite": True})
    assert m2.status_code == 200, m2.text

    # 6) load-saved menu reflects the overwrite.
    ms = client.get(
        f"{PREFIX}/menus/saved", params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME}
    )
    assert ms.status_code == 200
    cell = next(c for c in ms.json()["cells"] if c["product_id"] == product_id)
    assert cell["qty"] == 6

    # 7) opening-stock take (positive adjustment, reason mandatory).
    op = client.post(
        f"{PREFIX}/stock/opening-stock",
        json={"product_id": product_id, "qty": 20, "reason": f"{TAG}initial take"},
    )
    assert op.status_code == 201, op.text
    assert _balance(client, f"{TAG}P1") == 20

    # 8) import to dispatch (preview from saved menu).
    di = client.post(
        f"{PREFIX}/dispatches/import-from-menu",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME},
    )
    assert di.status_code == 200, di.text
    di_cell = next(c for c in di.json()["cells"] if c["product_id"] == product_id)
    assert di_cell["qty"] == 6

    # 9) save PLANNED dispatch - stock MUST NOT change.
    disp_save = {
        "year": YEAR,
        "week": WEEK,
        "day_name": DAY_NAME,
        "lines": [{"fridge_id": fridge_id, "product_id": product_id, "qty": 6}],
    }
    d1 = client.post(f"{PREFIX}/dispatches/save", json=disp_save)
    assert d1.status_code == 200, d1.text
    assert d1.json()["status"] == "saved"
    assert _balance(client, f"{TAG}P1") == 20  # planned save does not touch stock

    d_dup = client.post(f"{PREFIX}/dispatches/save", json=disp_save)
    assert d_dup.status_code == 409 and d_dup.json()["error"]["code"] == "exists"

    d2 = client.post(f"{PREFIX}/dispatches/save", json={**disp_save, "overwrite": True})
    assert d2.status_code == 200 and _balance(client, f"{TAG}P1") == 20

    # 10) load-saved dispatch.
    ds = client.get(
        f"{PREFIX}/dispatches/saved", params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME}
    )
    assert ds.status_code == 200 and ds.json()["status"] == "saved"

    # 11) create individual dispatch - the ONLY stock-writing path.
    ci = client.post(
        f"{PREFIX}/dispatches/create-individual",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME, "force": True},
    )
    assert ci.status_code == 200, ci.text
    assert ci.json()["status"] == "dispatched"
    assert ci.json()["movements_created"] == 1
    assert _balance(client, f"{TAG}P1") == 14  # 20 - 6

    # 12) draft PO from the saved menu, per supplier.
    po = client.post(
        f"{PREFIX}/menus/draft-purchase-orders",
        params={"year": YEAR, "week": WEEK, "day_name": DAY_NAME, "supplier_id": supplier_id},
    )
    assert po.status_code == 200, po.text
    po_body = po.json()
    assert po_body["supplier_id"] == supplier_id
    po_line = next(line for line in po_body["lines"] if line["product_id"] == product_id)
    assert po_line["qty_ordered"] == 6


def test_forecast_save_requires_delivery_config(ctx):
    """save with no fridge delivery config for the weekday -> 409 no_delivery_config."""
    resp = ctx.client.post(
        f"{PREFIX}/forecasts/save",
        json={"year": YEAR, "week": WEEK, "day_name": DAY_NAME, "fridge_ids": [-1]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_delivery_config"


def test_menu_import_without_saved_forecast_404(ctx):
    resp = ctx.client.post(
        f"{PREFIX}/menus/import-from-forecast",
        params={"year": YEAR, "week": 3, "day_name": DAY_NAME},
    )
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "not_found"


def test_bad_day_name_422(ctx):
    resp = ctx.client.get(
        f"{PREFIX}/forecasts/saved", params={"year": YEAR, "week": WEEK, "day_name": "Funday"}
    )
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"
