"""low_stock_check job against the local DB: it opens a low_stock alert for a product below minimum.

Every write happens inside one outer transaction that is rolled back, except the
job's own sync_run bookkeeping row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.db import engine
from cron.jobs import low_stock_check

PRODUCT_CODE = "ZZTEST-LOWSTOCK-JOB"
MIN_STOCK_QTY = 10
PHYSICAL_QTY = 3


@pytest.fixture()
def rolled_back_session_factory(monkeypatch):
    connection = engine.connect()
    outer_transaction = connection.begin()
    session_factory = sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    monkeypatch.setattr(low_stock_check, "SessionLocal", session_factory)
    try:
        yield session_factory
    finally:
        outer_transaction.rollback()
        connection.close()


def test_job_opens_one_alert_for_a_product_below_its_minimum(rolled_back_session_factory):
    with rolled_back_session_factory() as session, session.begin():
        product_id = _create_low_product(session)

    first_run = low_stock_check.run()
    second_run = low_stock_check.run()

    with rolled_back_session_factory() as session:
        alerts = session.execute(
            text(
                "SELECT status, payload FROM alerts "
                "WHERE alert_type = 'low_stock' AND (payload->>'product_id')::int = :product"
            ),
            {"product": product_id},
        ).all()
    assert first_run.opened >= 1
    assert second_run.opened == 0
    [alert] = alerts
    assert alert.status == "open"
    assert alert.payload["physical_qty"] == PHYSICAL_QTY
    assert alert.payload["min_stock_qty"] == MIN_STOCK_QTY


def _create_low_product(session: Session) -> int:
    product_id = session.execute(
        text(
            "INSERT INTO products (code, name, category_id, is_active, min_stock_qty) "
            "SELECT :code, :code, min(id), true, :minimum FROM categories "
            "RETURNING id"
        ),
        {"code": PRODUCT_CODE, "minimum": MIN_STOCK_QTY},
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO stock_movements (product_id, qty, movement_type, reason) "
            "VALUES (:product, :qty, 'adjustment', 'low stock job test')"
        ),
        {"product": product_id, "qty": PHYSICAL_QTY},
    )
    return product_id
