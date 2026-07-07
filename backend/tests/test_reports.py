"""Tests for the reports slice (D3): enriched fridge report, its Excel export,
and the product rating scorecard.

Strategy mirrors ``test_finance_routers``: integration tests run inside one outer
transaction rolled back on teardown (``join_transaction_mode="create_savepoint"``)
so committed service work is visible but never persisted; all seeded identifiers
are ZZTEST-prefixed. Aggregations scan the whole window (not just ZZTEST rows),
but each ZZTEST product/fridge is unique so its own totals are isolated.
"""

from __future__ import annotations

import datetime
import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.main import app
from app.models.enums import RestockAction, TagStatus
from app.models.events import ProductReview, RestockEvent, SalesEvent
from app.models.master import Category, Client, Fridge, Product, Supplier

UTC = datetime.timezone.utc

# A date inside the trailing-365-day scorecard window (today = 2026-07-03) with a
# pre-created monthly event partition.
EVENT_DAY = datetime.datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
REPORT_FROM = "2026-06-01"
REPORT_TO = "2026-06-30"


# ===========================================================================
# Fixtures
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
    """A ZZTEST supplier/category/product/fridge, IDs captured after flush."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.category_id = session.query(Category).order_by(Category.id).first().id

        supplier = Supplier(name="ZZTEST-report-supplier")
        client_row = Client(name="ZZTEST-report-client")
        session.add_all([supplier, client_row])
        session.flush()
        self.supplier_id = supplier.id
        self.client_id = client_row.id

        product = Product(
            code="ZZTEST-RPT-P1",
            name="ZZTEST Report Product",
            category_id=self.category_id,
            supplier_id=self.supplier_id,
            purchase_price=400,  # cents (EUR 4.00)
            sales_price=1060,    # cents (EUR 10.60) -> ex-VAT 10.00
            vat_rate=Decimal("0.06"),
            shelf_life_days=5,
        )
        session.add(product)
        session.flush()
        self.product_id = product.id

        fridge = Fridge(
            husky_id="ZZTEST-RPT-F1",
            friendly_name="ZZTEST-Report-Fridge1",
            client_id=self.client_id,
        )
        session.add(fridge)
        session.flush()
        self.fridge_id = fridge.id


@pytest.fixture()
def seed(db_session) -> Seed:
    return Seed(db_session)


def _add_sale(session, seed, sold_at, refunded=False) -> None:
    session.add(
        SalesEvent(
            husky_ref=f"ZZTEST-RPT-S-{sold_at.timestamp()}-{refunded}-{id(sold_at)}",
            fridge_id=seed.fridge_id,
            product_id=seed.product_id,
            sold_at=sold_at,
            unit_price=1060,  # cents (EUR 10.60)
            is_refunded=refunded,
        )
    )


def _add_restock(session, seed, occurred, tag_status, count) -> None:
    for index in range(count):
        session.add(
            RestockEvent(
                husky_ref=f"ZZTEST-RPT-R-{tag_status.value}-{index}-{occurred.timestamp()}",
                fridge_id=seed.fridge_id,
                product_id=seed.product_id,
                action=RestockAction.added,
                tag_status=tag_status,
                occurred_at=occurred,
            )
        )


def _add_reviews(session, seed, reviewed_at, positive, negative) -> None:
    for index in range(positive):
        session.add(
            ProductReview(
                husky_ref=f"ZZTEST-RPT-REV-pos-{index}-{reviewed_at.timestamp()}",
                product_id=seed.product_id,
                rating=1,
                reviewed_at=reviewed_at,
            )
        )
    for index in range(negative):
        session.add(
            ProductReview(
                husky_ref=f"ZZTEST-RPT-REV-neg-{index}-{reviewed_at.timestamp()}",
                product_id=seed.product_id,
                rating=-1,
                reviewed_at=reviewed_at,
            )
        )


# ===========================================================================
# Fridge report (JSON) — rows + summary
# ===========================================================================


def test_fridge_report_rows_and_summary(client, seed, db_session) -> None:
    _add_sale(db_session, seed, EVENT_DAY)
    _add_sale(db_session, seed, EVENT_DAY.replace(hour=10))
    _add_restock(db_session, seed, EVENT_DAY, TagStatus.valid, 2)  # 2 x 4.00
    db_session.flush()

    resp = client.get(
        f"/api/v1/finance/fridge-report?fridge_id={seed.fridge_id}"
        f"&from={REPORT_FROM}&to={REPORT_TO}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Summary KPIs.
    assert body["added_qty"] == 2
    assert body["food_cost"] == "8.00"
    assert body["revenue"] == "21.20"  # 2 x 10.60
    assert body["margin"] == "12.00"   # 21.20/1.06 - 8.00 = 20.00 - 8.00
    assert body["margin_pct"] == "60.00"  # 12.00 / 20.00 * 100

    # Per-product rows.
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["product_id"] == seed.product_id
    assert row["code"] == "ZZTEST-RPT-P1"
    assert row["name"] == "ZZTEST Report Product"
    assert row["added_qty"] == 2
    assert row["unit_buying_price"] == "4.00"
    assert row["unit_selling_price"] == "10.60"


# ===========================================================================
# Fridge report Excel export — summary on top, table below
# ===========================================================================


def test_fridge_report_export_xlsx(client, seed, db_session) -> None:
    _add_sale(db_session, seed, EVENT_DAY)
    _add_sale(db_session, seed, EVENT_DAY.replace(hour=10))
    _add_restock(db_session, seed, EVENT_DAY, TagStatus.valid, 2)
    db_session.flush()

    resp = client.get(
        f"/api/v1/finance/fridge-report/export.xlsx?fridge_id={seed.fridge_id}"
        f"&from={REPORT_FROM}&to={REPORT_TO}"
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in resp.headers["content-disposition"]
    assert f"fridge-report_{seed.fridge_id}_" in resp.headers["content-disposition"]
    assert resp.headers["content-disposition"].endswith('.xlsx"')

    # The bytes open cleanly in openpyxl.
    workbook = load_workbook(io.BytesIO(resp.content))
    worksheet = workbook["Fridge Report"]

    # Summary block sits at the very top.
    assert worksheet["A1"].value == "Fridge Report"
    assert worksheet["A2"].value == "Fridge"
    assert str(seed.fridge_id) in str(worksheet["B2"].value)
    assert worksheet["A3"].value == "Period"
    assert worksheet["A5"].value == "Total Added Qty"
    assert worksheet["B5"].value == 2
    assert worksheet["A6"].value == "Food Cost (EUR)"
    assert float(worksheet["B6"].value) == pytest.approx(8.00)
    assert worksheet["A7"].value == "Revenue (EUR)"
    assert float(worksheet["B7"].value) == pytest.approx(21.20)
    assert worksheet["A8"].value == "Food Margin (EUR)"
    assert float(worksheet["B8"].value) == pytest.approx(12.00)

    # The table body follows below the summary (header at the reserved anchor).
    assert worksheet["A11"].value == "Product"
    assert worksheet["B11"].value == "Code"
    assert worksheet["A12"].value == "ZZTEST Report Product"


# ===========================================================================
# Product rating scorecard
# ===========================================================================


def test_scorecard_math_spotcheck(client, seed, db_session) -> None:
    # sold=3 (1 refunded excluded), added=5 (1 unrecognised excluded),
    # reviews: 4 positive / 1 negative.
    for hour in (9, 10, 11):
        _add_sale(db_session, seed, EVENT_DAY.replace(hour=hour))
    _add_sale(db_session, seed, EVENT_DAY.replace(hour=12), refunded=True)
    _add_restock(db_session, seed, EVENT_DAY, TagStatus.valid, 5)
    _add_restock(db_session, seed, EVENT_DAY, TagStatus.unrecognised, 1)
    _add_reviews(db_session, seed, EVENT_DAY, positive=4, negative=1)
    db_session.flush()

    resp = client.get("/api/v1/rating/scorecard?limit=500&window_days=365")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Weights envelope (live scoring_weights).
    assert body["weights"] == {"pct_sold": "0.62", "margin": "0.33", "review": "0.05"}
    assert body["window_days"] == 365

    # Find our product across pages if needed.
    row = _find_scorecard_row(client, seed.product_id, body)
    assert row is not None, "seeded product missing from scorecard"

    # Hand computation.
    # pct_sold = 3 / 5 = 0.6
    # margin   = (1000 - 400) / 1000 = 0.6   (sell ex-VAT = 1060 / 1.06 = 1000)
    # review   = (4 - 1) / 5 = 0.6 ; pct_positive = 4 / 5 = 0.8
    # final    = 0.62*0.6 + 0.33*0.6 + 0.05*0.6 = 0.6
    assert row["total_sold_qty"] == 3
    assert row["total_added_qty"] == 5
    assert row["pct_sold"] == "0.6000"
    assert row["profit_margin"] == "0.6000"
    assert row["positive_reviews"] == 4
    assert row["negative_reviews"] == 1
    assert row["pct_positive_review"] == "0.8000"
    assert row["final_score"] == "0.6000"
    assert row["buying_price"] == "4.00"
    assert row["sold_price"] == "10.60"
    assert row["vat_rate"] == "0.0600"
    assert row["brand"] == "ZZTEST-report-supplier"
    assert row["shelf_life_days"] == 5


def _find_scorecard_row(client, product_id: int, first_page: dict) -> dict | None:
    for row in first_page["items"]:
        if row["product_id"] == product_id:
            return row
    total = first_page["total"]
    limit = first_page["limit"]
    offset = limit
    while offset < total:
        page = client.get(
            f"/api/v1/rating/scorecard?limit={limit}&offset={offset}"
        ).json()
        for row in page["items"]:
            if row["product_id"] == product_id:
                return row
        offset += limit
    return None


def test_scorecard_pagination_and_default_sort(client, seed) -> None:
    resp = client.get("/api/v1/rating/scorecard?limit=100")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] >= 500  # full catalogue
    assert body["limit"] == 100
    assert len(body["items"]) == 100

    # Default sort is final_score descending.
    scores = [Decimal(row["final_score"]) for row in body["items"]]
    assert scores == sorted(scores, reverse=True)


def test_scorecard_sort_ascending(client, seed) -> None:
    resp = client.get("/api/v1/rating/scorecard?limit=50&sort=final_score%20asc")
    assert resp.status_code == 200, resp.text
    scores = [Decimal(row["final_score"]) for row in resp.json()["items"]]
    assert scores == sorted(scores)


def test_scorecard_bad_sort_field_422(client) -> None:
    resp = client.get("/api/v1/rating/scorecard?sort=bogus")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable_entity"
