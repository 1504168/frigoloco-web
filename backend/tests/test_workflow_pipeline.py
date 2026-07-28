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

    # days_to_fill is derived from the rotation; a second delivery 3 days after
    # the run's weekday makes that weekday's days_to_fill resolve to 3.
    second_weekday = ((DELIVERY_WEEKDAY + 3 - 1) % 7) + 1
    client.put(
        f"{PREFIX}/fridges/{fridge_id}/delivery-config",
        json={
            "items": [
                {"weekday": DELIVERY_WEEKDAY, "min_daily_qty": 0},
                {"weekday": second_weekday, "min_daily_qty": 0},
            ]
        },
    )
    # 21 sales / 21 lookback days -> avg 1/day * days_to_fill 3 = 3.00 forecast.
    _seed_sales(session, fridge_id=fridge_id, product_id=product_id, days=21)

    # 1) run forecast: computes, is_saved=false. Scope to this fridge so the
    # assertion is hermetic - other fridges may share this weekday.
    run = client.post(
        f"{PREFIX}/forecasts/run",
        json={"delivery_date": DELIVERY_DATE.isoformat(), "fridge_ids": [fridge_id]},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["is_saved"] is False
    assert body["model"] == "moving_average_3w"
    assert (body["iso_year"], body["week_no"], body["day_name"]) == (YEAR, WEEK, DAY_NAME)
    normal_cell = next(
        r for r in body["results"] if r["fridge_id"] == fridge_id and r["category_id"] == cat
    )
    assert normal_cell["forecast_qty"] == "3.00"

    # 2) save forecast (persist keyed); overwrite-confirm. Scoped to this fridge.
    save_body = {"year": YEAR, "week": WEEK, "day_name": DAY_NAME, "fridge_ids": [fridge_id]}
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


# --- category-scoped save & pull (Excel "one category" flow) ----------------


def _two_normal_categories(session: Session) -> tuple[int, int]:
    rows = session.execute(
        text(
            "SELECT id FROM categories "
            "WHERE lower(name) NOT LIKE '%drink%' AND lower(name) NOT LIKE '%snack%' "
            "ORDER BY id LIMIT 2"
        )
    ).all()
    assert len(rows) >= 2, "need two non-drink/snack categories for the scope test"
    return rows[0].id, rows[1].id


def test_category_scoped_menu_save(ctx):
    """Saving a menu for one category leaves other categories' lines intact."""
    client, session = ctx.client, ctx.session
    cat_a, cat_b = _two_normal_categories(session)
    supplier_id = _create_supplier(client, f"{TAG}CatSup")
    product_a = _create_product(client, code=f"{TAG}CA", category_id=cat_a, supplier_id=supplier_id)
    product_b = _create_product(client, code=f"{TAG}CB", category_id=cat_b, supplier_id=supplier_id)
    fridge_id = _create_fridge(client, f"{TAG}catFr")

    base = {"year": YEAR, "week": WEEK, "day_name": DAY_NAME}

    # A) first category-scoped save creates the menu (no conflict, no overwrite).
    r_a = client.post(
        f"{PREFIX}/menus/save",
        json={**base, "category_id": cat_a, "lines": [{"fridge_id": fridge_id, "product_id": product_a, "qty": 5}]},
    )
    assert r_a.status_code == 200, r_a.text

    # B) a different category also saves without overwrite (its lines are empty).
    r_b = client.post(
        f"{PREFIX}/menus/save",
        json={**base, "category_id": cat_b, "lines": [{"fridge_id": fridge_id, "product_id": product_b, "qty": 7}]},
    )
    assert r_b.status_code == 200, r_b.text

    saved = client.get(f"{PREFIX}/menus/saved", params=base).json()["cells"]
    assert {c["product_id"]: c["qty"] for c in saved} == {product_a: 5, product_b: 7}

    # C) re-saving the SAME category without overwrite conflicts.
    dup = client.post(
        f"{PREFIX}/menus/save",
        json={**base, "category_id": cat_a, "lines": [{"fridge_id": fridge_id, "product_id": product_a, "qty": 9}]},
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "exists"

    # D) overwrite that one category; the other category is untouched.
    ow = client.post(
        f"{PREFIX}/menus/save",
        json={
            **base,
            "category_id": cat_a,
            "overwrite": True,
            "lines": [{"fridge_id": fridge_id, "product_id": product_a, "qty": 9}],
        },
    )
    assert ow.status_code == 200, ow.text
    saved2 = client.get(f"{PREFIX}/menus/saved", params=base).json()["cells"]
    assert {c["product_id"]: c["qty"] for c in saved2} == {product_a: 9, product_b: 7}

    # E) a scoped save whose lines fall outside the target category is rejected.
    bad = client.post(
        f"{PREFIX}/menus/save",
        json={
            **base,
            "category_id": cat_a,
            "overwrite": True,
            "lines": [{"fridge_id": fridge_id, "product_id": product_b, "qty": 3}],
        },
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"


def test_category_scoped_dispatch_save_and_import(ctx):
    """Category-scoped dispatch save preserves other categories; import filters."""
    client, session = ctx.client, ctx.session
    cat_a, cat_b = _two_normal_categories(session)
    supplier_id = _create_supplier(client, f"{TAG}DCatSup")
    product_a = _create_product(client, code=f"{TAG}DCA", category_id=cat_a, supplier_id=supplier_id)
    product_b = _create_product(client, code=f"{TAG}DCB", category_id=cat_b, supplier_id=supplier_id)
    fridge_id = _create_fridge(client, f"{TAG}dcatFr")

    base = {"year": YEAR, "week": WEEK, "day_name": DAY_NAME}

    # Build a saved MENU with both categories (source for import-from-menu).
    client.post(
        f"{PREFIX}/menus/save",
        json={
            **base,
            "lines": [
                {"fridge_id": fridge_id, "product_id": product_a, "qty": 4},
                {"fridge_id": fridge_id, "product_id": product_b, "qty": 8},
            ],
        },
    )

    # import-from-menu scoped to cat_a returns only cat_a cells/products.
    imp = client.post(
        f"{PREFIX}/dispatches/import-from-menu", params={**base, "category_id": cat_a}
    )
    assert imp.status_code == 200, imp.text
    assert {c["product_id"] for c in imp.json()["cells"]} == {product_a}
    assert {p["product_id"] for p in imp.json()["products"]} == {product_a}

    # Category-scoped planned saves accumulate across categories.
    d_a = client.post(
        f"{PREFIX}/dispatches/save",
        json={**base, "category_id": cat_a, "lines": [{"fridge_id": fridge_id, "product_id": product_a, "qty": 4}]},
    )
    assert d_a.status_code == 200, d_a.text
    d_b = client.post(
        f"{PREFIX}/dispatches/save",
        json={**base, "category_id": cat_b, "lines": [{"fridge_id": fridge_id, "product_id": product_b, "qty": 8}]},
    )
    assert d_b.status_code == 200, d_b.text

    dispatch_id = client.get(f"{PREFIX}/dispatches/saved", params=base).json()["id"]
    matrix = client.get(f"{PREFIX}/dispatches/{dispatch_id}/matrix").json()["cells"]
    assert {c["product_id"]: c["qty"] for c in matrix} == {product_a: 4, product_b: 8}

    # Re-saving cat_a without overwrite conflicts; overwrite keeps cat_b intact.
    dup = client.post(
        f"{PREFIX}/dispatches/save",
        json={**base, "category_id": cat_a, "lines": [{"fridge_id": fridge_id, "product_id": product_a, "qty": 6}]},
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "exists"

    ow = client.post(
        f"{PREFIX}/dispatches/save",
        json={
            **base,
            "category_id": cat_a,
            "overwrite": True,
            "lines": [{"fridge_id": fridge_id, "product_id": product_a, "qty": 6}],
        },
    )
    assert ow.status_code == 200, ow.text
    matrix2 = client.get(f"{PREFIX}/dispatches/{dispatch_id}/matrix").json()["cells"]
    assert {c["product_id"]: c["qty"] for c in matrix2} == {product_a: 6, product_b: 8}

    # Lines outside the target category are rejected.
    bad = client.post(
        f"{PREFIX}/dispatches/save",
        json={
            **base,
            "category_id": cat_a,
            "overwrite": True,
            "lines": [{"fridge_id": fridge_id, "product_id": product_b, "qty": 2}],
        },
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
