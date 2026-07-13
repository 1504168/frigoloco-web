"""Tests for the Husky sync domain layer + sync API (work-order D5).

Two tiers:

* Pure tests - the field-ownership contract guard, the effective-status rule and
  its SQL clause. No DB, no network.
* Live-DB transactional tests - bound to one connection inside an outer
  transaction rolled back on teardown (mirrors ``test_ops_routers``), proving a
  manual ``local_status`` override survives a catalogue upsert while the
  Husky-owned columns refresh, plus the ``?status=`` filter and ``/sync/runs``.

The sync API POST is exercised with the domain functions and ``create_sync_run``
monkeypatched, so no live vendor call or out-of-transaction write happens.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.husky.schemas import ProductTypeItem
from app.husky.sync import (
    FRIDGE_HUSKY_OWNED,
    FRIDGE_PRODUCT_PRICE_HUSKY_OWNED,
    PRODUCT_HUSKY_OWNED,
    JobOutcome,
    SyncContractError,
    _apply_product_types,
    _guarded_update_set,
    effective_status,
    effective_status_clause,
)
from app.main import app
from app.models import Fridge, Product

PREFIX = "/api/v1"
TAG = "ZZTEST-"


# ===========================================================================
# Pure: field-ownership contract
# ===========================================================================


def test_local_status_never_husky_owned() -> None:
    # The manual override must not appear in ANY Husky-owned list.
    assert "local_status" not in PRODUCT_HUSKY_OWNED
    assert "local_status" not in FRIDGE_HUSKY_OWNED
    assert "local_status" not in FRIDGE_PRODUCT_PRICE_HUSKY_OWNED


def test_guarded_update_set_allows_husky_and_sync_columns() -> None:
    ok = _guarded_update_set("products", {"name": "x", "sales_price": 1, "is_active": True})
    assert ok == {"name": "x", "sales_price": 1, "is_active": True}


def test_guarded_update_set_rejects_local_status() -> None:
    with pytest.raises(SyncContractError):
        _guarded_update_set("products", {"name": "x", "local_status": "cancelled"})
    with pytest.raises(SyncContractError):
        _guarded_update_set("fridges", {"local_status": "inactive"})


def test_guarded_update_set_rejects_local_only_columns() -> None:
    # delivery_* are local-owned on fridges - sync must never write them.
    with pytest.raises(SyncContractError):
        _guarded_update_set("fridges", {"delivery_address": "somewhere"})


# ===========================================================================
# Pure: effective-status rule + clause
# ===========================================================================


@pytest.mark.parametrize(
    "local_status, is_active, expected",
    [
        (None, True, "active"),
        (None, False, "inactive"),
        ("inactive", True, "inactive"),  # override wins even when Husky-active
        ("cancelled", True, "cancelled"),
        ("cancelled", False, "cancelled"),
    ],
)
def test_effective_status_rule(local_status, is_active, expected) -> None:
    assert effective_status(local_status, is_active) == expected


def test_effective_status_clause_none_for_all_and_missing() -> None:
    assert effective_status_clause(Product, None) is None
    assert effective_status_clause(Product, "all") is None
    assert effective_status_clause(Product, "bogus") is None


def test_effective_status_clause_builds_for_known_states() -> None:
    for status in ("active", "inactive", "cancelled"):
        assert effective_status_clause(Product, status) is not None
        assert effective_status_clause(Fridge, status) is not None


# ===========================================================================
# Live-DB fixture (rolled back on teardown)
# ===========================================================================


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


def _any_category_id(session: Session) -> int:
    return session.execute(text("SELECT id FROM categories ORDER BY id LIMIT 1")).scalar_one()


# ===========================================================================
# Live-DB: local_status survives a catalogue upsert (the core D5 guarantee)
# ===========================================================================


def test_local_status_survives_catalogue_upsert(ctx) -> None:
    session = ctx.session
    category_id = _any_category_id(session)
    code = f"{TAG}CAT-001"

    # A product the user has manually CANCELLED, previously synced from Husky.
    session.add(
        Product(
            code=code,
            name="OLD NAME",
            category_id=category_id,
            sales_price=100,
            is_active=True,
            local_status="cancelled",
            husky_synced_at=datetime.datetime.now(datetime.timezone.utc),
        )
    )
    session.flush()

    # Husky returns the same code with a fresh name/price -> catalogue upsert.
    outcome = JobOutcome()
    item = ProductTypeItem(
        productCode=code,
        name="NEW HUSKY NAME",
        productCategory=None,
        price=999,
        vat=6.0,
        expiryDays=5,
    )
    _apply_product_types(session, [item], outcome)
    session.flush()

    refreshed = session.execute(
        text("SELECT name, sales_price, is_active, local_status FROM products WHERE code = :c"),
        {"c": code},
    ).one()
    # Husky-owned columns refreshed …
    assert refreshed.name == "NEW HUSKY NAME"
    assert refreshed.sales_price == 999
    assert refreshed.is_active is True
    # … but the manual override is UNTOUCHED (still cancelled = effective status).
    assert refreshed.local_status == "cancelled"


# ===========================================================================
# Live-DB: producttype.reference (euro string) ingests as purchase_price cents
# ===========================================================================


def test_reference_ingested_as_purchase_price_cents(ctx) -> None:
    """The Husky `reference` field is the BUY price as a euro DECIMAL STRING.

    It must land in products.purchase_price scaled to BIGINT cents (euros * 100),
    NOT stored raw like `price` (already cents). Regression guard for the bug
    where all 1,017 products had purchase_price=0 because `reference` was ignored.
    """
    session = ctx.session
    code = f"{TAG}BUY-001"
    outcome = JobOutcome()
    item = ProductTypeItem(
        productCode=code,
        name="Salade Cesar C&G (test)",
        productCategory=None,
        reference="5.95",  # euro decimal string -> 595 cents
        price=960,          # sales price already in cents (€9.60)
        vat=6.0,
        expiryDays=5,
    )
    _apply_product_types(session, [item], outcome)
    session.flush()

    row = session.execute(
        text("SELECT purchase_price, sales_price FROM products WHERE code = :c"),
        {"c": code},
    ).one()
    assert row.purchase_price == 595  # €5.95 -> 595 cents (NOT stored raw as 5)
    assert row.sales_price == 960     # price stays raw cents


# ===========================================================================
# Live-DB: ?status= filter honours the override
# ===========================================================================


def test_products_status_filter_honours_override(ctx) -> None:
    session = ctx.session
    category_id = _any_category_id(session)
    active_code = f"{TAG}FILT-ACTIVE"
    cancelled_code = f"{TAG}FILT-CANCELLED"
    session.add_all(
        [
            Product(code=active_code, name=f"{TAG}filter active", category_id=category_id, is_active=True),
            Product(
                code=cancelled_code,
                name=f"{TAG}filter cancelled",
                category_id=category_id,
                is_active=True,
                local_status="cancelled",
            ),
        ]
    )
    session.flush()

    def codes(status: str) -> set[str]:
        resp = ctx.client.get(
            f"{PREFIX}/products", params={"status": status, "search": f"{TAG}filter", "limit": 500}
        )
        assert resp.status_code == 200, resp.text
        return {item["code"] for item in resp.json()["items"]}

    assert cancelled_code in codes("cancelled")
    assert active_code not in codes("cancelled")
    assert active_code in codes("active")
    assert cancelled_code not in codes("active")
    # 'all' returns both.
    both = codes("all")
    assert {active_code, cancelled_code} <= both


def test_products_read_exposes_effective_status(ctx) -> None:
    session = ctx.session
    category_id = _any_category_id(session)
    code = f"{TAG}EFF-001"
    session.add(
        Product(code=code, name=f"{TAG}eff", category_id=category_id, is_active=True, local_status="inactive")
    )
    session.flush()
    resp = ctx.client.get(f"{PREFIX}/products", params={"search": code, "limit": 10})
    assert resp.status_code == 200, resp.text
    item = next(i for i in resp.json()["items"] if i["code"] == code)
    assert item["local_status"] == "inactive"
    assert item["effective_status"] == "inactive"


# ===========================================================================
# Sync API: POST returns a run id immediately; GET lists checkpoints
# ===========================================================================


def test_trigger_sync_returns_run_id_without_network(ctx, monkeypatch) -> None:
    from app.routers import husky_sync as sync_router

    calls: dict[str, int] = {}
    monkeypatch.setattr(sync_router, "create_sync_run", lambda *a, **k: 4242)

    def _fake_catalogue(run_id=None):
        calls["run_id"] = run_id
        return JobOutcome(fetched=1, upserted=1)

    monkeypatch.setattr(sync_router, "sync_catalogue", _fake_catalogue)

    resp = ctx.client.post(f"{PREFIX}/sync/husky/catalogue")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sync_run_id"] == 4242
    assert body["feed"] == "catalogue"
    assert body["status"] == "running"
    # Background task ran the (stubbed) domain function against the created id.
    assert calls.get("run_id") == 4242


def test_trigger_sync_rejects_unknown_feed(ctx) -> None:
    resp = ctx.client.post(f"{PREFIX}/sync/husky/nonsense")
    assert resp.status_code == 422, resp.text


def test_list_sync_runs_returns_checkpoints(ctx) -> None:
    session = ctx.session
    session.execute(
        text(
            "INSERT INTO sync_run (job, endpoint, status, records_fetched, records_upserted) "
            "VALUES (:j, :e, 'success', 5, 5)"
        ),
        {"j": f"{TAG}job", "e": f"{TAG}catalogue"},
    )
    session.flush()
    resp = ctx.client.get(f"{PREFIX}/sync/runs", params={"endpoint": f"{TAG}catalogue", "limit": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert all(row["endpoint"] == f"{TAG}catalogue" for row in body["items"])
    assert body["items"][0]["status"] == "success"
