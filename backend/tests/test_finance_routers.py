"""Tests for the supply + finance half of the API.

Strategy: one pure parity unit test (no DB), then integration tests against the
live Railway database. Integration tests are non-destructive - every test runs
inside a single outer transaction that is rolled back on teardown (the
``join_transaction_mode="create_savepoint"`` recipe), so committed service work
is visible within the test but never persisted. All seeded identifiers are
ZZTEST-prefixed as a second belt-and-braces guard.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.main import app
from app.models.enums import (
    AlertType,
    DispatchStatus,
    RestockAction,
    TagStatus,
)
from app.models.events import RestockEvent, SalesEvent
from app.models.master import (
    Category,
    Client,
    ClientFee,
    Fridge,
    Product,
    Supplier,
)
from app.models.operations import Alert, Dispatch, DispatchLine, StockMovement
from app.money import cents_to_euro_str
from app.schemas.orders import PoLineCreate
from app.services.orders_service import compute_po_totals

UTC = datetime.timezone.utc

# A synthetic ISO week with NO real Husky data: 2027-01-06 is a Wednesday in ISO
# week 1 of 2027 (future relative to the backfill/live window, and within the
# pre-created 2027-01 event partitions). Finance/verification aggregations scan
# the whole window, not just ZZTEST rows, so the anchor week must be empty.
SYNTHETIC_DAY = datetime.date(2027, 1, 6)


# ===========================================================================
# Parity unit test (no database)
# ===========================================================================


def test_po_totals_parity_order_2026_00360() -> None:
    """Order 2026-00360 shape: 3 lines at 6% VAT → 239.36 / 14.36 / 253.72."""
    lines = [
        PoLineCreate(product_id=1, qty=4, unit_price=Decimal("25.00"), vat_rate=Decimal("0.06")),
        PoLineCreate(product_id=2, qty=16, unit_price=Decimal("4.96"), vat_rate=Decimal("0.06")),
        PoLineCreate(product_id=3, qty=10, unit_price=Decimal("6.00"), vat_rate=Decimal("0.06")),
    ]
    totals = compute_po_totals(lines)
    # Totals are integer cents; the API-level euro strings must still be the
    # verified parity anchor 239.36 / 14.36 / 253.72.
    assert totals.ex_vat == 23936
    assert totals.vat == 1436
    assert totals.incl_vat == 25372
    assert cents_to_euro_str(totals.ex_vat) == "239.36"
    assert cents_to_euro_str(totals.vat) == "14.36"
    assert cents_to_euro_str(totals.incl_vat) == "253.72"


# ===========================================================================
# Integration fixtures
# ===========================================================================


@pytest.fixture()
def db_session():
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture()
def client(db_session):
    return TestClient(app)


class Seed:
    """Reference rows for a test, all ZZTEST-prefixed; IDs captured after flush."""

    def __init__(self, session: Session) -> None:
        self.session = session
        category = session.query(Category).order_by(Category.id).first()
        self.category_id = category.id

        supplier = Supplier(name="ZZTEST-supplier")
        client_row = Client(name="ZZTEST-client")
        session.add_all([supplier, client_row])
        session.flush()
        self.supplier_id = supplier.id
        self.client_id = client_row.id

        product = Product(
            code="ZZTEST-P1",
            name="ZZTEST Product",
            category_id=self.category_id,
            supplier_id=self.supplier_id,
            purchase_price=400,   # cents (EUR 4.00)
            sales_price=1060,     # cents (EUR 10.60)
            vat_rate=Decimal("0.06"),
            shelf_life_days=5,
        )
        session.add(product)
        session.flush()
        self.product_id = product.id

        fridge = Fridge(
            husky_id="ZZTEST-F1",
            friendly_name="ZZTEST-Fridge1",
            client_id=self.client_id,
        )
        session.add(fridge)
        session.flush()
        self.fridge_id = fridge.id


@pytest.fixture()
def seed(db_session) -> Seed:
    return Seed(db_session)


def _po_payload(seed: Seed, qty: int = 5) -> dict:
    today = datetime.date.today()
    return {
        "supplier_id": seed.supplier_id,
        "order_date": today.isoformat(),
        "expected_delivery_date": (today + datetime.timedelta(days=7)).isoformat(),
        "delivery_address": "ZZTEST-address",
        "comment": "ZZTEST",
        "lines": [
            {
                "product_id": seed.product_id,
                "qty": qty,
                "unit_price": "4.00",
                "vat_rate": "0.06",
            }
        ],
    }


# ===========================================================================
# Purchase orders
# ===========================================================================


def test_create_and_get_purchase_order(client, seed) -> None:
    resp = client.post("/api/v1/purchase-orders", json=_po_payload(seed))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["order_no"].startswith(f"{datetime.date.today().year}-")
    assert len(body["order_no"]) == 10  # YYYY-NNNNN
    assert body["total_ex_vat"] == "20.00"
    assert body["total_vat"] == "1.20"
    assert body["total_incl_vat"] == "21.20"
    assert body["status"] == "pending"

    got = client.get(f"/api/v1/purchase-orders/{body['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]


def test_po_lines_embed_product_code_and_name(client, seed) -> None:
    """PO line reads carry the joined product code + name (not just #id)."""
    resp = client.post("/api/v1/purchase-orders", json=_po_payload(seed))
    assert resp.status_code == 201, resp.text
    line = resp.json()["lines"][0]
    assert line["product_id"] == seed.product_id
    assert line["product_code"] == "ZZTEST-P1"
    assert line["product_name"] == "ZZTEST Product"
    # And on the standalone GET path too.
    got = client.get(f"/api/v1/purchase-orders/{resp.json()['id']}")
    assert got.json()["lines"][0]["product_code"] == "ZZTEST-P1"


def test_create_po_past_order_date_422(client, seed) -> None:
    payload = _po_payload(seed)
    payload["order_date"] = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    resp = client.post("/api/v1/purchase-orders", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable_entity"


def test_receive_full_flips_status_and_adds_stock(client, seed, db_session) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=5)).json()
    line_id = po["lines"][0]["id"]
    resp = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"received": [{"po_line_id": line_id, "qty_received": 5}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["order"]["status"] == "received"
    assert len(body["movements"]) == 1
    assert body["movements"][0]["qty"] == 5
    assert body["movements"][0]["movement_type"] == "po_receipt"

    balance = _stock_balance(db_session, seed.product_id)
    assert balance == 5


def test_over_receipt_requires_acknowledgement(client, seed) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=5)).json()
    line_id = po["lines"][0]["id"]
    blocked = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"received": [{"po_line_id": line_id, "qty_received": 7}]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "over_receipt"

    ok = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={
            "received": [{"po_line_id": line_id, "qty_received": 7}],
            "acknowledge_over_receipt": True,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["order"]["status"] == "received"


def test_cancel_pending_po_no_reversal(client, seed) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed)).json()
    resp = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["order"]["status"] == "cancelled"
    assert body["previous_status"] == "pending"
    assert body["reversal_movements"] == []


def test_cancel_received_po_reverses_stock(client, seed, db_session) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=5)).json()
    line_id = po["lines"][0]["id"]
    client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"received": [{"po_line_id": line_id, "qty_received": 5}]},
    )
    assert _stock_balance(db_session, seed.product_id) == 5

    resp = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["order"]["status"] == "cancelled"
    assert body["previous_status"] == "received"
    assert len(body["reversal_movements"]) == 1
    assert body["reversal_movements"][0]["qty"] == -5
    assert _stock_balance(db_session, seed.product_id) == 0


def _stock_balance(session: Session, product_id: int) -> int:
    return int(
        session.execute(
            select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
                StockMovement.product_id == product_id
            )
        ).scalar_one()
    )


# ===========================================================================
# Verifications (R9)
# ===========================================================================


def test_verify_dispatch_computes_diff(client, seed, db_session) -> None:
    # Pinned to a synthetic empty week (no real Husky data): the reconciliation
    # scans ALL restock events in the delivery-day window, not just ZZTEST rows.
    delivery = SYNTHETIC_DAY
    dispatch = Dispatch(
        delivery_date=delivery,
        iso_week=delivery.isocalendar()[1],
        weekday=delivery.isocalendar()[2],
        status=DispatchStatus.draft,
    )
    db_session.add(dispatch)
    db_session.flush()
    db_session.add(
        DispatchLine(
            dispatch_id=dispatch.id,
            fridge_id=seed.fridge_id,
            product_id=seed.product_id,
            delivery_date=delivery,  # denormalised partition key
            qty=10,
            unit_purchase_price=400,  # cents (EUR 4.00)
        )
    )
    occurred = datetime.datetime(delivery.year, delivery.month, delivery.day, 10, 0, tzinfo=UTC)
    _add_restock(db_session, seed, occurred, TagStatus.valid, 8)
    _add_restock(db_session, seed, occurred, TagStatus.unreliable, 2)
    _add_restock(db_session, seed, occurred, TagStatus.unrecognised, 3)
    db_session.flush()

    resp = client.post(f"/api/v1/dispatches/{dispatch.id}/verify")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["dispatched_qty"] == 10
    assert line["added_qty"] == 8       # valid only
    assert line["unreliable_qty"] == 2  # tracked separately
    assert line["diff_qty"] == -2       # 8 - 10, unrecognised excluded
    assert line["diff_value"] == "-8.00"

    listing = client.get(f"/api/v1/verifications?dispatch_id={dispatch.id}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    detail = client.get(f"/api/v1/verifications/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["lines"][0]["diff_qty"] == -2


def _add_restock(session, seed, occurred, tag_status, count) -> None:
    for i in range(count):
        session.add(
            RestockEvent(
                husky_ref=f"ZZTEST-R-{tag_status.value}-{i}-{occurred.timestamp()}",
                fridge_id=seed.fridge_id,
                product_id=seed.product_id,
                action=RestockAction.added,
                tag_status=tag_status,
                occurred_at=occurred,
            )
        )


# ===========================================================================
# Finance
# ===========================================================================


def _add_sale(session, seed, sold_at, refunded=False) -> None:
    session.add(
        SalesEvent(
            husky_ref=f"ZZTEST-S-{sold_at.timestamp()}-{refunded}-{id(sold_at)}",
            fridge_id=seed.fridge_id,
            product_id=seed.product_id,
            sold_at=sold_at,
            unit_price=1060,  # cents (EUR 10.60)
            is_refunded=refunded,
        )
    )


def test_weekly_pnl_formulas(client, seed, db_session) -> None:
    # Pinned to a synthetic empty week: the weekly P&L sums ALL sales_events in
    # the ISO-week window, not just ZZTEST rows, so the week must carry no real
    # backfilled data or the KPI assertions below would drift.
    day = datetime.datetime(SYNTHETIC_DAY.year, SYNTHETIC_DAY.month, SYNTHETIC_DAY.day, 9, 0, tzinfo=UTC)
    year, week, _ = day.date().isocalendar()
    _add_sale(db_session, seed, day)
    _add_sale(db_session, seed, day.replace(hour=10))
    _add_sale(db_session, seed, day.replace(hour=11), refunded=True)
    _add_restock(db_session, seed, day, TagStatus.valid, 2)  # food cost 2 x 4.00
    db_session.flush()

    put = client.put(
        f"/api/v1/finance/weekly/{year}/{week}",
        json={
            "catering_turnover": "100.00",
            "catering_food_cost": "30.00",
            "tgtg_turnover": "50.00",
            "logistics_cost": "20.00",
            "drops_count": 3,
            "unsold_items": 1,
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["gross_sales"] == "31.80"
    assert body["refunds"] == "10.60"
    assert body["items_sold"] == 2
    assert body["turnover_ex_vat"] == "20.00"       # (31.80 - 10.60)/1.06
    assert body["fridge_food_cost_added"] == "8.00"  # 2 x 4.00
    assert body["pos_fee"] == "2.86"                 # 0.09 x 31.80
    assert body["rfid_fee"] == "0.20"                # 0.10 x 2
    assert body["net_margin"] == "108.94"

    got = client.get(f"/api/v1/finance/weekly/{year}/{week}")
    assert got.status_code == 200
    assert got.json()["net_margin"] == "108.94"


def test_weekly_fridge_count_roundtrip(client, seed) -> None:
    """The manual weekly fridge_count input round-trips through PUT and GET."""
    year, week = 2027, 5
    put = client.put(
        f"/api/v1/finance/weekly/{year}/{week}",
        json={"fridge_count": 12},
    )
    assert put.status_code == 200, put.text
    assert put.json()["inputs"]["fridge_count"] == 12

    got = client.get(f"/api/v1/finance/weekly/{year}/{week}")
    assert got.status_code == 200, got.text
    assert got.json()["inputs"]["fridge_count"] == 12


def test_monthly_client_dimension(client, seed, db_session) -> None:
    db_session.add(
        ClientFee(
            client_id=seed.client_id,
            yearly_fee=120000,  # cents (EUR 1200.00)
            contract_start=datetime.date(2026, 1, 1),
            contract_end=None,
        )
    )
    delivery = datetime.date(2026, 6, 17)
    dispatch = Dispatch(
        delivery_date=delivery,
        iso_week=delivery.isocalendar()[1],
        weekday=delivery.isocalendar()[2],
        status=DispatchStatus.draft,
    )
    db_session.add(dispatch)
    db_session.flush()
    db_session.add(
        DispatchLine(
            dispatch_id=dispatch.id,
            fridge_id=seed.fridge_id,
            product_id=seed.product_id,
            delivery_date=delivery,  # denormalised partition key
            qty=10,
            unit_purchase_price=400,   # cents (EUR 4.00)
            unit_sales_price=1060,     # cents (EUR 10.60)
            vat_rate=Decimal("0.06"),
        )
    )
    _add_sale(db_session, seed, datetime.datetime(2026, 6, 17, 9, tzinfo=UTC))
    db_session.flush()

    resp = client.get("/api/v1/finance/monthly?dimension=client&month=2026-06")
    assert resp.status_code == 200, resp.text
    rows = {r["key_id"]: r for r in resp.json()["rows"]}
    assert seed.client_id in rows
    row = rows[seed.client_id]
    assert row["fee_share"] == "100.00"  # 1200 / 12
    # food_margin = 10 x (10.60/1.06 - 4.00) = 10 x 6.00 = 60.00
    assert row["food_margin"] == "60.00"


def test_monthly_bad_dimension_422(client) -> None:
    resp = client.get("/api/v1/finance/monthly?dimension=bogus&month=2026-06")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable_entity"


def test_fridge_gsv_report(client, seed, db_session) -> None:
    day = datetime.datetime(2026, 6, 17, 9, tzinfo=UTC)
    _add_sale(db_session, seed, day)
    _add_sale(db_session, seed, day.replace(hour=10))
    _add_restock(db_session, seed, day, TagStatus.valid, 2)
    db_session.flush()

    resp = client.get(
        f"/api/v1/finance/fridge-report?fridge_id={seed.fridge_id}"
        "&from=2026-06-01&to=2026-06-30"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["added_qty"] == 2
    assert body["food_cost"] == "8.00"
    assert body["revenue"] == "21.20"      # 2 x 10.60
    assert body["margin"] == "12.00"       # 21.20/1.06 - 8.00


# ===========================================================================
# Alerts & settings
# ===========================================================================


def test_alerts_list_and_ack(client, seed, db_session) -> None:
    alert = Alert(
        alert_type=AlertType.below_target,
        payload={"note": "ZZTEST"},
        status="open",
    )
    db_session.add(alert)
    db_session.flush()
    alert_id = alert.id

    listing = client.get("/api/v1/alerts?acknowledged=false")
    assert listing.status_code == 200
    assert any(a["id"] == alert_id for a in listing.json()["items"])

    ack = client.put(f"/api/v1/alerts/{alert_id}/ack")
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledged_at"] is not None


def test_settings_put_roundtrip(client) -> None:
    resp = client.put(
        "/api/v1/settings/ZZTEST_flag",
        json={"value": {"enabled": True, "n": 5}, "description": "ZZTEST"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"] == "ZZTEST_flag"
    assert body["value"] == {"enabled": True, "n": 5}

    listing = client.get("/api/v1/settings")
    assert any(s["key"] == "ZZTEST_flag" for s in listing.json())
