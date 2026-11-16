"""Tests for the restock (#56) and loss (#57) reports.

No database: a fake session hands canned rows to the loaders in query order and
records each statement, so the SQL is checked by compiling it for PostgreSQL.
"""

from __future__ import annotations

import datetime
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy.dialects import postgresql

from app.db import get_db
from app.main import app
from app.services import ops_reports_service
from app.services.ops_reports_service import ReportScope

DAY_ONE = datetime.date(2026, 11, 2)
DAY_TWO = datetime.date(2026, 11, 3)
FRIDGE_ID = 7
SANDWICH_ID = 11
SALAD_ID = 12
SANDWICH_PRICE_CENTS = 250
SALAD_PRICE_CENTS = 310
SCOPE = ReportScope(date_from=DAY_ONE, date_to=DAY_TWO)

FRIDGE_ROWS = [(FRIDGE_ID, "Thermofisher")]
PRODUCT_ROWS = [
    (SANDWICH_ID, "0042", "Sandwich", "Food", SANDWICH_PRICE_CENTS),
    (SALAD_ID, "1001", "Salad", "Food", SALAD_PRICE_CENTS),
]


class FakeResult:
    def __init__(self, records: list[tuple]) -> None:
        self.records = records

    def all(self) -> list[tuple]:
        return self.records


class FakeSession:
    def __init__(self, answers: list[list[tuple]]) -> None:
        self.answers = list(answers)
        self.statements: list[str] = []

    def execute(self, statement) -> FakeResult:
        compiled = statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
        self.statements.append(str(compiled))
        return FakeResult(self.answers.pop(0))


@pytest.fixture()
def client_with_session():
    def install(session: FakeSession) -> TestClient:
        app.dependency_overrides[get_db] = lambda: session
        return TestClient(app)

    yield install
    app.dependency_overrides.pop(get_db, None)


def build_restock_session() -> FakeSession:
    dispatched = [
        (DAY_ONE, FRIDGE_ID, SANDWICH_ID, 5),
        (DAY_TWO, FRIDGE_ID, SALAD_ID, 3),
    ]
    added = [
        (DAY_ONE, FRIDGE_ID, SANDWICH_ID, 4),
        (DAY_ONE, FRIDGE_ID, SALAD_ID, 2),
    ]
    return FakeSession([dispatched, added, FRIDGE_ROWS, PRODUCT_ROWS])


def build_loss_session() -> FakeSession:
    removed = [
        (DAY_ONE, FRIDGE_ID, SANDWICH_ID, 2),
        (DAY_ONE, FRIDGE_ID, SALAD_ID, 1),
    ]
    return FakeSession([removed, FRIDGE_ROWS, PRODUCT_ROWS])


def test_restock_report_keeps_rows_found_on_only_one_side():
    session = build_restock_session()

    report_rows = ops_reports_service.load_restock_report(session, SCOPE)
    report = ops_reports_service.build_restock_report_read(report_rows, SCOPE)

    quantities_by_day_product = {
        (row.delivery_date, row.product_name): (row.dispatched_qty, row.added_qty, row.gap_qty)
        for row in report.rows
    }
    assert quantities_by_day_product == {
        (DAY_ONE, "Salad"): (0, 2, 2),
        (DAY_ONE, "Sandwich"): (5, 4, -1),
        (DAY_TWO, "Salad"): (3, 0, -3),
    }
    assert report.total_dispatched_qty == 8
    assert report.total_added_qty == 6
    assert report.total_gap_qty == -2
    assert report.rows[0].product_code == "1001"


def test_restock_queries_use_shipped_dispatches_and_valid_added_brussels_days():
    session = build_restock_session()

    ops_reports_service.load_restock_report(session, SCOPE)

    dispatched_sql, added_sql = session.statements[:2]
    assert "'dispatched'" in dispatched_sql
    assert "'reconciled'" in dispatched_sql
    assert "'saved'" not in dispatched_sql
    assert "timezone('Europe/Brussels', restock_events.occurred_at)" in added_sql
    assert "'added'" in added_sql
    assert "'valid'" in added_sql
    assert "2026-11-02 00:00:00+01:00" in added_sql
    assert "2026-11-04 00:00:00+01:00" in added_sql


def test_scope_filters_reach_both_queries():
    session = build_restock_session()
    scope = ReportScope(
        date_from=DAY_ONE,
        date_to=DAY_TWO,
        fridge_id=FRIDGE_ID,
        category_id=3,
    )

    ops_reports_service.load_restock_report(session, scope)

    for statement in session.statements[:2]:
        assert f"fridge_id = {FRIDGE_ID}" in statement
        assert "products.category_id = 3" in statement


def test_loss_report_values_removed_units_at_purchase_price_per_iso_week():
    session = build_loss_session()

    report_rows = ops_reports_service.load_loss_report(session, SCOPE)
    report = ops_reports_service.build_loss_report_read(report_rows, SCOPE)

    assert "'removed'" in session.statements[0]
    assert "date_trunc('week'" in session.statements[0]
    assert {(row.iso_year, row.iso_week) for row in report.rows} == {(2026, 45)}
    assert report.total_removed_qty == 3
    assert report.model_dump(mode="json")["total_loss_cost"] == "8.10"


def test_reversed_range_is_rejected(client_with_session):
    client = client_with_session(FakeSession([]))

    response = client.get("/api/v1/reports/loss", params={"from": "2026-11-05", "to": "2026-11-01"})

    assert response.status_code == 422


def test_restock_endpoint_returns_rows_and_totals(client_with_session):
    client = client_with_session(build_restock_session())

    response = client.get(
        "/api/v1/reports/restock",
        params={"from": "2026-11-02", "to": "2026-11-03"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 3
    assert body["total_gap_qty"] == -2


def test_loss_export_writes_euro_values_and_totals(client_with_session):
    client = client_with_session(build_loss_session())

    response = client.get(
        "/api/v1/reports/loss/export.xlsx",
        params={"from": "2026-11-02", "to": "2026-11-03"},
    )

    assert response.status_code == 200
    assert "loss-report_2026-11-02_2026-11-03.xlsx" in response.headers["content-disposition"]
    sheet = load_workbook(io.BytesIO(response.content)).active
    header = [cell.value for cell in sheet[1]]
    loss_column = header.index("Loss cost (EUR)") + 1
    loss_values = [sheet.cell(row=row_number, column=loss_column).value for row_number in (2, 3)]
    assert sorted(loss_values) == [3.1, 5.0]


def test_restock_export_handles_an_empty_range(client_with_session):
    client = client_with_session(FakeSession([[], [], [], []]))

    response = client.get(
        "/api/v1/reports/restock/export.xlsx",
        params={"from": "2026-11-02", "to": "2026-11-03"},
    )

    assert response.status_code == 200
    assert load_workbook(io.BytesIO(response.content)).active.title == "Restock report"
