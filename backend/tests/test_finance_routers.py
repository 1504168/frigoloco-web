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
import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.main import app
from app.models.enums import (
    AlertType,
    DispatchStatus,
    RestockAction,
    StockMovementType,
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
from app.models.operations import (
    Alert,
    AuditLog,
    Dispatch,
    DispatchLine,
    StockMovement,
    WeeklyFinancial,
)
from app.money import cents_to_euro_str, to_cents
from app.schemas.orders import RECEIPT_COMMENT_MAX_LENGTH
from app.services.finance_service import LOCAL_TIMEZONE
from app.services.orders_service import PricedPoLine, compute_po_totals
from tests import TEST_ADMIN_USER, ensure_dispatches_week_start, ensure_test_admin_user

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
        PricedPoLine(product_id=1, qty=4, unit_price_cents=2500, vat_rate=Decimal("0.06")),
        PricedPoLine(product_id=2, qty=16, unit_price_cents=496, vat_rate=Decimal("0.06")),
        PricedPoLine(product_id=3, qty=10, unit_price_cents=600, vat_rate=Decimal("0.06")),
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
    ensure_dispatches_week_start(connection)
    ensure_test_admin_user(connection)
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
        "lines": [{"product_id": seed.product_id, "qty": qty}],
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


def test_create_po_ignores_client_price_and_vat(client, seed) -> None:
    """Unit price and VAT are copied from the catalogue (EUR 4.00, 6%), never the client."""
    payload = _po_payload(seed, qty=5)
    payload["lines"][0]["unit_price"] = "99.99"
    payload["lines"][0]["vat_rate"] = "0.21"
    resp = client.post("/api/v1/purchase-orders", json=payload)
    assert resp.status_code == 201, resp.text
    line = resp.json()["lines"][0]
    assert line["unit_price"] == "4.00"
    assert Decimal(line["vat_rate"]) == Decimal("0.06")
    assert resp.json()["total_incl_vat"] == "21.20"


def test_create_po_rejects_product_of_other_supplier(client, seed, db_session) -> None:
    other_supplier = Supplier(name="ZZTEST-other-supplier")
    db_session.add(other_supplier)
    db_session.flush()
    payload = _po_payload(seed)
    payload["supplier_id"] = other_supplier.id
    resp = client.post("/api/v1/purchase-orders", json=payload)
    assert resp.status_code == 422
    assert "not supplied by this supplier" in resp.json()["error"]["message"]


def test_cancel_partly_received_po_reverses_stock(client, seed, db_session) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=10)).json()
    line_id = po["lines"][0]["id"]
    received = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"received": [{"po_line_id": line_id, "qty_received": 4}]},
    )
    assert received.json()["order"]["status"] == "pending"
    assert _stock_balance(db_session, seed.product_id) == 4

    resp = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["previous_status"] == "pending"
    assert [movement["qty"] for movement in body["reversal_movements"]] == [-4]
    assert _stock_balance(db_session, seed.product_id) == 0


def test_receipt_comments_listed_per_partial_receipt(client, seed, db_session) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=10)).json()
    line_id = po["lines"][0]["id"]
    receive_url = f"/api/v1/purchase-orders/{po['id']}/receive"
    first = client.post(
        receive_url,
        json={
            "received": [{"po_line_id": line_id, "qty_received": 4}],
            "comment": "  2 boxes broken  ",
        },
    )
    assert first.json()["order"]["status"] == "pending"
    second = client.post(
        receive_url,
        json={"received": [{"po_line_id": line_id, "qty_received": 6}], "comment": ""},
    )
    assert second.json()["order"]["status"] == "received"

    resp = client.get(f"/api/v1/purchase-orders/{po['id']}/receipts")
    assert resp.status_code == 200, resp.text
    receipts = resp.json()
    assert [receipt["comment"] for receipt in receipts] == [None, "2 boxes broken"]
    assert [receipt["lines"][0]["qty_received"] for receipt in receipts] == [6, 4]
    assert receipts[0]["created_by_name"] is not None

    cancel = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel")
    assert cancel.status_code == 200, cancel.text
    assert [movement["qty"] for movement in cancel.json()["reversal_movements"]] == [-10]
    assert _stock_balance(db_session, seed.product_id) == 0


def test_receipt_comment_too_long_422(client, seed) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed)).json()
    resp = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={
            "received": [{"po_line_id": po["lines"][0]["id"], "qty_received": 5}],
            "comment": "x" * (RECEIPT_COMMENT_MAX_LENGTH + 1),
        },
    )
    assert resp.status_code == 422


def test_cancel_partly_received_po_blocked_when_stock_used(client, seed, db_session) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed, qty=10)).json()
    line_id = po["lines"][0]["id"]
    client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        json={"received": [{"po_line_id": line_id, "qty_received": 4}]},
    )
    db_session.add(
        StockMovement(
            product_id=seed.product_id,
            qty=-3,
            movement_type=StockMovementType.adjustment,
            reason="ZZTEST stock used",
        )
    )
    db_session.commit()

    resp = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "cancel_blocked"


def test_list_purchase_orders_search_by_order_no_and_supplier(client, seed) -> None:
    po = client.post("/api/v1/purchase-orders", json=_po_payload(seed)).json()

    by_supplier = client.get(
        "/api/v1/purchase-orders",
        params={"search": "zztest-SUPPLIER"},
    ).json()
    assert [item["id"] for item in by_supplier["items"]] == [po["id"]]
    assert by_supplier["total"] == 1

    by_order_no = client.get(
        "/api/v1/purchase-orders",
        params={"search": po["order_no"]},
    ).json()
    assert by_order_no["total"] == 1
    assert by_order_no["items"][0]["id"] == po["id"]


def _stock_balance(session: Session, product_id: int) -> int:
    return int(
        session.execute(
            select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
                StockMovement.product_id == product_id
            )
        ).scalar_one()
    )


# NOTE (2026-07-28): Restock verification (legacy R9) removed. The dispatch
# `/verify` test was deleted with it. `_add_restock` (below) is kept - it is shared
# by the finance tests. Dispatched-vs-added reconciliation will return later as a
# DERIVED, period-level report over dispatch_lines + restock_events, not per-dispatch.


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
    _add_dispatch_line(db_session, seed, delivery, DispatchStatus.dispatched, qty=10)
    # One dispatch per delivery date: the unconfirmed ones go on the following days.
    draft_day = delivery + datetime.timedelta(days=1)
    saved_day = delivery + datetime.timedelta(days=2)
    _add_dispatch_line(db_session, seed, draft_day, DispatchStatus.draft, qty=99)
    _add_dispatch_line(db_session, seed, saved_day, DispatchStatus.saved, qty=99)
    _add_sale(db_session, seed, datetime.datetime(2026, 6, 17, 9, tzinfo=UTC))
    db_session.flush()

    resp = client.get("/api/v1/finance/monthly?dimension=client&month=2026-06")
    assert resp.status_code == 200, resp.text
    rows = {r["key_id"]: r for r in resp.json()["rows"]}
    assert seed.client_id in rows
    row = rows[seed.client_id]
    assert row["key_name"] == "ZZTEST-client"
    assert row["fridge_count"] == 1
    assert row["fee_share"] == "100.00"  # 1200 / 12
    # Only the dispatched line counts: 10 x (10.60/1.06 - 4.00) = 10 x 6.00 = 60.00
    assert row["food_margin"] == "60.00"
    assert row["sales"] == "10.60"
    assert row["sales_ex_vat"] == "10.00"


def _add_dispatch_line(
    session: Session,
    seed: Seed,
    delivery: datetime.date,
    status: DispatchStatus,
    qty: int,
) -> None:
    iso_date = delivery.isocalendar()
    confirmed = status in (DispatchStatus.dispatched, DispatchStatus.reconciled)
    dispatch = Dispatch(
        delivery_date=delivery,
        iso_week=iso_date.week,
        weekday=iso_date.weekday,
        status=status,
        confirmed_at=datetime.datetime.now(UTC) if confirmed else None,
    )
    session.add(dispatch)
    session.flush()
    session.add(
        DispatchLine(
            dispatch_id=dispatch.id,
            fridge_id=seed.fridge_id,
            product_id=seed.product_id,
            delivery_date=delivery,  # denormalised partition key
            qty=qty,
            unit_purchase_price=400,   # cents (EUR 4.00)
            unit_sales_price=1060,     # cents (EUR 10.60)
            vat_rate=Decimal("0.06"),
        )
    )


def _active_fridge_count(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(Fridge).where(
            Fridge.is_active.is_(True),
            Fridge.local_status.is_(None),
        )
    ).scalar_one()


def test_monthly_logistics_prorated_over_month_weeks(client, seed, db_session) -> None:
    # March 2027: ISO W9..W12 lie fully inside it, W13 (29 Mar - 4 Apr) has 3 days in it.
    weekly_logistics_cents = 7000  # EUR 70.00 per week
    for iso_year, iso_week in ((2027, 12), (2027, 13), (2027, 14), (2027, 30)):
        db_session.add(
            WeeklyFinancial(
                year=iso_year,
                iso_week=iso_week,
                logistics_cost=weekly_logistics_cents,
            )
        )
    db_session.flush()

    resp = client.get("/api/v1/finance/monthly?dimension=client&month=2027-03")
    assert resp.status_code == 200, resp.text
    rows = {r["key_id"]: r for r in resp.json()["rows"]}

    month_logistics_cents = Decimal(7000) + Decimal(7000) * 3 / 7  # EUR 100.00
    expected_share = to_cents(month_logistics_cents / _active_fridge_count(db_session))
    assert rows[seed.client_id]["logistics_share"] == cents_to_euro_str(expected_share)


def test_monthly_fridge_dimension_splits_client_charges(client, seed, db_session) -> None:
    second_fridge = Fridge(
        husky_id="ZZTEST-F2",
        friendly_name="ZZTEST-Fridge2",
        client_id=seed.client_id,
    )
    unassigned_fridge = Fridge(husky_id="ZZTEST-F3", friendly_name="ZZTEST-Fridge3")
    db_session.add_all([second_fridge, unassigned_fridge])
    db_session.add(
        ClientFee(
            client_id=seed.client_id,
            yearly_fee=120000,  # EUR 1200.00 -> 100.00 / month
            contract_start=datetime.date(2027, 1, 1),
            contract_end=None,
        )
    )
    db_session.flush()
    db_session.add(
        SalesEvent(
            husky_ref="ZZTEST-S-unassigned",
            fridge_id=unassigned_fridge.id,
            product_id=seed.product_id,
            sold_at=datetime.datetime(2027, 3, 10, 9, tzinfo=UTC),
            unit_price=1060,
            is_refunded=False,
        )
    )
    db_session.flush()

    by_fridge = client.get("/api/v1/finance/monthly?dimension=fridge&month=2027-03")
    assert by_fridge.status_code == 200, by_fridge.text
    fridge_rows = {r["key_id"]: r for r in by_fridge.json()["rows"]}
    assert fridge_rows[seed.fridge_id]["fee_share"] == "50.00"
    assert fridge_rows[second_fridge.id]["fee_share"] == "50.00"
    assert fridge_rows[seed.fridge_id]["client_name"] == "ZZTEST-client"
    assert fridge_rows[unassigned_fridge.id]["client_name"] == "No client"
    assert fridge_rows[unassigned_fridge.id]["fee_share"] == "0.00"
    assert fridge_rows[unassigned_fridge.id]["sales"] == "10.60"

    by_client = client.get("/api/v1/finance/monthly?dimension=client&month=2027-03")
    client_rows = {r["key_id"]: r for r in by_client.json()["rows"]}
    assert client_rows[seed.client_id]["fridge_count"] == 2
    assert client_rows[seed.client_id]["fee_share"] == "100.00"
    assert client_rows[None]["key_name"] == "No client"
    assert by_client.json()["rows"][-1]["key_name"] == "No client"


def test_weekly_window_uses_brussels_days(client, seed, db_session) -> None:
    # 2027-01-10 is the Sunday ending ISO week 1 of 2027. Brussels is UTC+1 in January.
    sunday_late_evening = datetime.datetime(2027, 1, 10, 22, 30, tzinfo=UTC)  # 23:30 local
    next_monday_early = datetime.datetime(2027, 1, 10, 23, 30, tzinfo=UTC)  # 00:30 local
    _add_sale(db_session, seed, sunday_late_evening)
    _add_sale(db_session, seed, next_monday_early)
    db_session.flush()

    week_1 = client.get("/api/v1/finance/weekly/2027/1").json()
    week_2 = client.get("/api/v1/finance/weekly/2027/2").json()
    assert week_1["gross_sales"] == "10.60"
    assert week_2["gross_sales"] == "10.60"
    assert week_1["in_progress"] is False


def test_weekly_current_week_is_in_progress(client) -> None:
    today = datetime.datetime.now(LOCAL_TIMEZONE).date()
    iso_today = today.isocalendar()
    resp = client.get(f"/api/v1/finance/weekly/{iso_today.year}/{iso_today.week}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["in_progress"] is True


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
    assert body["revenue_ex_vat"] == "20.00"  # 21.20/1.06
    assert body["margin"] == "12.00"       # 20.00 - 8.00


def test_all_fridges_report_rows_totals_and_export(client, seed, db_session) -> None:
    day = datetime.datetime.combine(SYNTHETIC_DAY, datetime.time(9), tzinfo=UTC)
    _add_sale(db_session, seed, day)
    _add_sale(db_session, seed, day.replace(hour=10))
    _add_restock(db_session, seed, day, TagStatus.valid, 2)
    db_session.flush()
    report_range = {"from": SYNTHETIC_DAY.isoformat(), "to": SYNTHETIC_DAY.isoformat()}

    resp = client.get("/api/v1/finance/all-fridges-report", params=report_range)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = {row["fridge_id"]: row for row in body["rows"]}
    row = rows[seed.fridge_id]
    assert row["fridge_name"] == "ZZTEST-Fridge1"
    assert row["client_name"] == "ZZTEST-client"
    assert row["added_qty"] == 2
    assert row["food_cost"] == "8.00"
    assert row["revenue"] == "21.20"
    assert row["revenue_ex_vat"] == "20.00"
    assert row["margin"] == "12.00"
    assert row["margin_pct"] == "0.6000"
    total_added_qty = sum(fridge_row["added_qty"] for fridge_row in body["rows"])
    assert body["totals"]["added_qty"] == total_added_qty

    export = client.get("/api/v1/finance/all-fridges-report/export.xlsx", params=report_range)
    assert export.status_code == 200, export.text
    assert "all-fridges-report_" in export.headers["content-disposition"]
    worksheet = load_workbook(io.BytesIO(export.content))["All Fridges Report"]
    assert worksheet["A1"].value == "All Fridges Report"
    assert worksheet["A11"].value == "Fridge"
    exported_fridges = [cell.value for cell in worksheet["A"][11:]]
    assert "ZZTEST-Fridge1" in exported_fridges


def test_all_fridges_report_rejects_inverted_range(client) -> None:
    resp = client.get(
        "/api/v1/finance/all-fridges-report",
        params={"from": "2027-01-10", "to": "2027-01-01"},
    )
    assert resp.status_code == 422


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
    assert ack.json()["acknowledged_by"] == TEST_ADMIN_USER.id


def test_alert_second_ack_is_a_no_op(client, db_session) -> None:
    alert = Alert(
        alert_type=AlertType.below_target,
        payload={"note": "ZZTEST"},
        status="open",
    )
    db_session.add(alert)
    db_session.flush()
    alert_id = alert.id
    alert_audit_rows = (
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity == "alert", AuditLog.entity_id == str(alert_id))
    )

    first_ack = client.put(f"/api/v1/alerts/{alert_id}/ack")
    second_ack = client.put(f"/api/v1/alerts/{alert_id}/ack")

    assert second_ack.status_code == 200
    assert second_ack.json() == first_ack.json()
    assert db_session.execute(alert_audit_rows).scalar_one() == 1


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
