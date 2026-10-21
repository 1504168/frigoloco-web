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
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.husky.schemas import ProductTypeItem
from app.husky import sync as husky_sync
from app.husky.sync import (
    FRIDGE_HUSKY_OWNED,
    FRIDGE_PRODUCT_PRICE_HUSKY_OWNED,
    PRODUCT_HUSKY_OWNED,
    JobOutcome,
    SyncContractError,
    _apply_fridge_product_prices,
    _apply_fridges,
    _apply_product_types,
    _copy_text,
    _get_or_create_category,
    _guarded_update_set,
    _upsert_reviews,
    category_display_order,
    effective_status,
    effective_status_clause,
    snapshot_stock,
    sync_catalogue,
    sync_prices,
    sync_purchases_window,
    sync_restock_window,
    sync_reviews_window,
)
from app.main import app
from app.models import Category, Client, Fridge, FridgeProductPrice, FridgeStock, Product
from app.services.menu_allocation_service import _fridge_stock_readings

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
    # fridge_stock is created by migration 0009; create it here when the migration
    # has not been applied to this database yet (checkfirst -> no-op afterwards).
    # The DDL is inside the outer transaction and is rolled back on teardown.
    FridgeStock.__table__.create(bind=connection, checkfirst=True)

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


def _product_id(session: Session, code: str) -> int:
    return session.execute(
        text("SELECT id FROM products WHERE code = :c"), {"c": code}
    ).scalar_one()


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
# Live-DB: extra Husky fields retained store-only (migration 0010)
# ===========================================================================


def test_producttype_extra_fields_persist(ctx) -> None:
    """description / currency_code / price_ex_surcharges from /producttype store."""
    session = ctx.session
    code = f"{TAG}EXTRA-001"
    item = ProductTypeItem(
        productCode=code,
        name="Extra fields product",
        productCategory=None,
        description="Chilled falafel salad, 250g",
        currencyCode="EUR",
        price=960,             # sales price, raw cents
        priceExSurcharges=900,  # raw cents, before POS/RFID surcharges
        vat=6.0,
    )
    _apply_product_types(session, [item], JobOutcome())
    session.flush()

    row = session.execute(
        text(
            "SELECT description, currency_code, price_ex_surcharges "
            "FROM products WHERE code = :c"
        ),
        {"c": code},
    ).one()
    assert row.description == "Chilled falafel salad, 250g"
    assert row.currency_code == "EUR"
    assert row.price_ex_surcharges == 900  # stored RAW cents, not the surcharged price


def test_productreview_extra_fields_persist(ctx) -> None:
    """The full /productreview payload (free text, reviewer, purchase, tag) stores."""
    session = ctx.session
    code = f"{TAG}REV-001"
    _apply_product_types(
        session,
        [ProductTypeItem(productCode=code, name="Rev product", productCategory=None)],
        JobOutcome(),
    )
    session.flush()
    product_id = session.execute(
        text("SELECT id FROM products WHERE code = :c"), {"c": code}
    ).scalar_one()

    ref = f"{TAG}rev-ref-1"
    _upsert_reviews(
        session,
        [
            {
                "husky_ref": ref,
                "product_id": product_id,
                "fridge_id": None,
                "rating": 1,
                "reviewed_at": datetime.datetime(
                    2026, 6, 1, 12, tzinfo=datetime.timezone.utc
                ),
                "review_text": "Loved it, super fresh",
                "reviewer_email": "customer@example.com",
                "purchase_id": "PUR-123",
                "purchased_at": datetime.datetime(
                    2026, 5, 31, 9, tzinfo=datetime.timezone.utc
                ),
                "review_category": "1. Cold Dishes",
                "tag_id": "TAG-abc",
                "epc": "EPC-xyz",
                "product_reference": "REF-001",
            }
        ],
    )
    session.flush()

    row = session.execute(
        text(
            "SELECT review_text, reviewer_email, purchase_id, purchased_at, "
            "review_category, tag_id, epc, product_reference "
            "FROM product_reviews WHERE husky_ref = :r"
        ),
        {"r": ref},
    ).one()
    assert row.review_text == "Loved it, super fresh"
    assert row.reviewer_email == "customer@example.com"
    assert row.purchase_id == "PUR-123"
    assert row.review_category == "1. Cold Dishes"
    assert row.tag_id == "TAG-abc"
    assert row.epc == "EPC-xyz"
    assert row.product_reference == "REF-001"


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


# ===========================================================================
# Live-DB: fridge_stock mark-and-sweep (latest-only in-fridge stock, 0009)
# ===========================================================================


def _fake_stock_payload(units_by_fridge: dict[str, dict[str, int]]) -> SimpleNamespace:
    """Minimal stand-in for HuskyClient.get_stock_current()'s FetchResult.

    ``units_by_fridge`` maps fridge alias -> {product_code: units}. A fridge left
    out of the mapping is a fridge the vendor did not report on.
    """
    entries = [
        SimpleNamespace(
            fridge=SimpleNamespace(name=fridge_name, friendlyName=fridge_name),
            products=[
                SimpleNamespace(
                    productCode=code,
                    current=[f"tag-{code}-{i}" for i in range(units)],
                )
                for code, units in units_by_code.items()
            ],
        )
        for fridge_name, units_by_code in units_by_fridge.items()
    ]
    return SimpleNamespace(raw={"current": []}, data=SimpleNamespace(current=entries))


def _stock_snapshot_env(ctx, monkeypatch, payload: SimpleNamespace) -> None:
    """Run snapshot_stock against the test connection, with no vendor call.

    ``SessionLocal`` is redirected at the fixture's connection (savepoint-joined,
    so every commit inside the job is rolled back on teardown), the vendor client
    returns ``payload``, and the raw archive is stubbed.
    """
    connection = ctx.session.get_bind()

    def _session_factory() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def get_stock_current(self) -> SimpleNamespace:
            return payload

    monkeypatch.setattr(husky_sync, "SessionLocal", _session_factory)
    monkeypatch.setattr(husky_sync, "HuskyClient", _FakeClient)
    monkeypatch.setattr(husky_sync, "archive_raw", lambda *a, **k: "raw/husky/test.json.gz")


def _seed_stock_fridge(session: Session, suffix: str) -> Fridge:
    fridge = Fridge(
        husky_id=f"{TAG}if-{suffix}",
        friendly_name=f"{TAG}Fridge-{suffix}",
        is_active=True,
    )
    session.add(fridge)
    session.flush()
    return fridge


def _seed_stock_products(session: Session, codes: list[str]) -> None:
    category_id = _any_category_id(session)
    for code in codes:
        session.add(
            Product(code=code, name=f"{TAG}{code}", category_id=category_id, sales_price=100)
        )
    session.flush()


def _fridge_stock_rows(session: Session, fridge_id: int) -> dict[str, tuple[int, object]]:
    rows = session.execute(
        text("SELECT product_code, units, taken_at FROM fridge_stock WHERE fridge_id = :f"),
        {"f": fridge_id},
    ).all()
    return {row.product_code: (row.units, row.taken_at) for row in rows}


def test_snapshot_stock_upserts_then_sweeps_orphans(ctx, monkeypatch) -> None:
    session = ctx.session
    code_a, code_b = f"{TAG}SC-A", f"{TAG}SC-B"
    _seed_stock_products(session, [code_a, code_b])
    fridge = _seed_stock_fridge(session, "sweep")

    # Generation 1: both products are in the fridge.
    _stock_snapshot_env(
        ctx, monkeypatch, _fake_stock_payload({fridge.husky_id: {code_a: 3, code_b: 2}})
    )
    first = snapshot_stock()
    assert first.upserted == 2
    rows = _fridge_stock_rows(session, fridge.id)
    assert {code: units for code, (units, _) in rows.items()} == {code_a: 3, code_b: 2}
    generation_1 = rows[code_a][1]
    assert rows[code_b][1] == generation_1  # one shared taken_at per run

    # Generation 2: product B was pulled out of the fridge -> its row must be swept,
    # not left behind with stale units > 0 (which would make allocation under-dispatch).
    _stock_snapshot_env(
        ctx, monkeypatch, _fake_stock_payload({fridge.husky_id: {code_a: 1}})
    )
    second = snapshot_stock()
    assert second.upserted == 1
    rows = _fridge_stock_rows(session, fridge.id)
    assert set(rows) == {code_a}
    assert rows[code_a][0] == 1
    assert rows[code_a][1] > generation_1
    assert any("swept=1" in note for note in second.notes), second.notes


def test_snapshot_stock_partial_payload_keeps_unreported_fridge_and_flags_it(
    ctx, monkeypatch
) -> None:
    """A vendor response covering only SOME fridges must not empty the others.

    The unreported fridge keeps its rows with their OLD generation, which is what
    makes the allocation reader flag it stale instead of dispatching it to full
    target on a phantom live = 0.
    """
    session = ctx.session
    code_a, code_gone = f"{TAG}SC-PA", f"{TAG}SC-PG"
    _seed_stock_products(session, [code_a, code_gone])
    reported = _seed_stock_fridge(session, "reported")
    unreported = _seed_stock_fridge(session, "offline")

    # Generation 1 (3h ago): both fridges report, both products present.
    old_generation = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
    _stock_snapshot_env(
        ctx,
        monkeypatch,
        _fake_stock_payload(
            {
                reported.husky_id: {code_a: 3, code_gone: 2},
                unreported.husky_id: {code_a: 4},
            }
        ),
    )
    first = snapshot_stock(taken_at=old_generation)
    assert first.upserted == 3

    # Generation 2 (now): only the first fridge is in the payload, and code_gone has
    # been pulled out of it. The second fridge's RFID reader is offline.
    _stock_snapshot_env(
        ctx, monkeypatch, _fake_stock_payload({reported.husky_id: {code_a: 1}})
    )
    second = snapshot_stock()
    assert second.upserted == 1
    assert any("swept=1" in note for note in second.notes), second.notes

    # Reported fridge: orphan swept, survivor refreshed.
    reported_rows = _fridge_stock_rows(session, reported.id)
    assert set(reported_rows) == {code_a}
    assert reported_rows[code_a][0] == 1

    # Unreported fridge: rows SURVIVE, untouched, still on the old generation.
    unreported_rows = _fridge_stock_rows(session, unreported.id)
    assert set(unreported_rows) == {code_a}
    assert unreported_rows[code_a][0] == 4
    assert unreported_rows[code_a][1] == old_generation

    # ... and the allocation reader flags exactly that fridge as stale.
    readings = _fridge_stock_readings([reported.id, unreported.id], session)
    now = datetime.datetime.now(datetime.timezone.utc)
    assert readings.is_stale(reported.id, now) is False
    assert readings.is_stale(unreported.id, now) is True
    assert readings.units(unreported.id, _product_id(session, code_a)) == 4


def test_snapshot_stock_empty_payload_never_wipes_fridge_stock(ctx, monkeypatch) -> None:
    session = ctx.session
    code_a = f"{TAG}SC-KEEP"
    _seed_stock_products(session, [code_a])
    fridge = _seed_stock_fridge(session, "keep")

    _stock_snapshot_env(
        ctx, monkeypatch, _fake_stock_payload({fridge.husky_id: {code_a: 4}})
    )
    snapshot_stock()
    assert _fridge_stock_rows(session, fridge.id)[code_a][0] == 4

    # An empty vendor response means a vendor problem, NOT "every fridge is empty":
    # the sweep must be skipped and the table left untouched.
    empty = SimpleNamespace(raw={"current": []}, data=SimpleNamespace(current=[]))
    _stock_snapshot_env(ctx, monkeypatch, empty)
    outcome = snapshot_stock()
    assert outcome.upserted == 0
    assert any("swept=0" in note for note in outcome.notes), outcome.notes
    assert _fridge_stock_rows(session, fridge.id)[code_a][0] == 4


# ===========================================================================
# Category display order + fridge client assignment
# ===========================================================================


@pytest.mark.parametrize(
    "category_name, expected_order",
    [
        ("1. Cold Dishes", 1),
        ("10. Frozen Warm Dishes", 10),
        ("11. Baguettes", 11),
        ("Uncategorised", 999),
        ("Seasonal", 999),
    ],
)
def test_category_display_order_uses_number_prefix(category_name, expected_order) -> None:
    assert category_display_order(category_name) == expected_order


def test_new_category_lands_at_its_number_prefix(ctx) -> None:
    category_id, created = _get_or_create_category(ctx.session, f"42. {TAG}Soups", {})

    assert created
    assert ctx.session.get(Category, category_id).display_order == 42


def _sync_fake_fridges(session: Session, fridges: list[SimpleNamespace]) -> None:
    _apply_fridges(session, fridges, JobOutcome())
    session.expire_all()


def _husky_fridge(husky_id: str, facility: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        name=husky_id,
        description=None,
        friendlyName=f"{husky_id}-name",
        facility=facility,
    )


def test_fridge_sync_keeps_manual_client_and_fills_empty_one(ctx) -> None:
    session = ctx.session
    facility_client = Client(name=f"{TAG}Facility client")
    manual_client = Client(name=f"{TAG}Manual client")
    session.add_all([facility_client, manual_client])
    session.flush()
    manually_assigned = Fridge(
        husky_id=f"{TAG}if-manual",
        friendly_name=f"{TAG}if-manual-name",
        client_id=manual_client.id,
        is_active=True,
    )
    unassigned = Fridge(
        husky_id=f"{TAG}if-empty",
        friendly_name=f"{TAG}if-empty-name",
        is_active=True,
    )
    no_facility_match = Fridge(
        husky_id=f"{TAG}if-nomatch",
        friendly_name=f"{TAG}if-nomatch-name",
        client_id=manual_client.id,
        is_active=True,
    )
    session.add_all([manually_assigned, unassigned, no_facility_match])
    session.flush()

    _sync_fake_fridges(
        session,
        [
            _husky_fridge(manually_assigned.husky_id, facility_client.name),
            _husky_fridge(unassigned.husky_id, facility_client.name),
            _husky_fridge(no_facility_match.husky_id, f"{TAG}Unknown facility"),
        ],
    )

    assert session.get(Fridge, manually_assigned.id).client_id == manual_client.id
    assert session.get(Fridge, unassigned.id).client_id == facility_client.id
    assert session.get(Fridge, no_facility_match.id).client_id == manual_client.id


# ===========================================================================
# fridge_product_prices: the feed only overwrites the extras it carried
# ===========================================================================


def _fridge_price_entry(husky_id: str, prices: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(name=husky_id, friendlyName=None, prices=prices)


def _price_item(
    code: str,
    price: int,
    price_ex_surcharges: int | None = None,
    vat: float | None = None,
    currency_code: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        productCode=code,
        price=price,
        priceExSurcharges=price_ex_surcharges,
        vat=vat,
        currencyCode=currency_code,
    )


def _stored_fridge_price(session: Session, fridge_id: int, product_id: int) -> FridgeProductPrice:
    session.expire_all()
    return session.get(FridgeProductPrice, (fridge_id, product_id))


def test_fridge_price_sync_keeps_extras_the_feed_left_out(ctx) -> None:
    session = ctx.session
    code = f"{TAG}FPP-001"
    _seed_stock_products(session, [code])
    product_id = _product_id(session, code)
    fridge = _seed_stock_fridge(session, "prices")

    first_payload = [
        _fridge_price_entry(
            fridge.husky_id,
            [_price_item(code, 500, price_ex_surcharges=450, vat=6.0, currency_code="EUR")],
        )
    ]
    outcome = JobOutcome()
    _apply_fridge_product_prices(session, first_payload, outcome)
    stored = _stored_fridge_price(session, fridge.id, product_id)
    stored_values = (stored.sales_price, stored.price_ex_surcharges, stored.currency_code)
    assert stored_values == (500, 450, "EUR")
    assert float(stored.vat_rate) == 0.06
    assert outcome.upserted == 1

    price_only_payload = [_fridge_price_entry(fridge.husky_id, [_price_item(code, 650)])]
    _apply_fridge_product_prices(session, price_only_payload, JobOutcome())
    stored = _stored_fridge_price(session, fridge.id, product_id)
    assert stored.sales_price == 650
    assert (stored.price_ex_surcharges, stored.currency_code) == (450, "EUR")
    assert float(stored.vat_rate) == 0.06

    refreshed_payload = [
        _fridge_price_entry(
            fridge.husky_id,
            [_price_item(code, 700, price_ex_surcharges=600, vat=21.0, currency_code="USD")],
        )
    ]
    _apply_fridge_product_prices(session, refreshed_payload, JobOutcome())
    stored = _stored_fridge_price(session, fridge.id, product_id)
    stored_values = (stored.sales_price, stored.price_ex_surcharges, stored.currency_code)
    assert stored_values == (700, 600, "USD")
    assert float(stored.vat_rate) == 0.21


def test_fridge_price_listed_twice_merges_like_two_upserts(ctx) -> None:
    session = ctx.session
    code = f"{TAG}FPP-DUP"
    _seed_stock_products(session, [code])
    fridge = _seed_stock_fridge(session, "prices-dup")
    payload = [
        _fridge_price_entry(
            fridge.husky_id,
            [
                _price_item(code, 500, price_ex_surcharges=450, currency_code="EUR"),
                _price_item(code, 520),
            ],
        )
    ]
    outcome = JobOutcome()
    _apply_fridge_product_prices(session, payload, outcome)

    stored = _stored_fridge_price(session, fridge.id, _product_id(session, code))
    stored_values = (stored.sales_price, stored.price_ex_surcharges, stored.currency_code)
    assert stored_values == (520, 450, "EUR")
    assert outcome.upserted == 2


def test_product_sync_keeps_price_the_feed_left_out(ctx) -> None:
    session = ctx.session
    code = f"{TAG}PRICE-KEEP"
    priced_item = ProductTypeItem(productCode=code, name="Priced", productCategory=None, price=960)
    unpriced_item = ProductTypeItem(productCode=code, name="Renamed", productCategory=None)
    _apply_product_types(session, [priced_item], JobOutcome())
    _apply_product_types(session, [unpriced_item], JobOutcome())

    row = session.execute(
        text("SELECT name, sales_price FROM products WHERE code = :c"),
        {"c": code},
    ).one()
    assert row.name == "Renamed"
    assert row.sales_price == 960


# ===========================================================================
# Every sync fetches from Husky before it opens a DB transaction
# ===========================================================================


class _EmptyHuskyClient:
    """Returns an empty payload per endpoint and fails if a DB transaction is open."""

    open_sessions: list[Session] = []
    endpoints_called: list[str] = []

    def __enter__(self) -> "_EmptyHuskyClient":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def _empty(self, endpoint: str, **payload: object) -> SimpleNamespace:
        busy_sessions = [session for session in self.open_sessions if session.in_transaction()]
        assert busy_sessions == [], f"{endpoint} fetched while a DB transaction was open"
        self.endpoints_called.append(endpoint)
        return SimpleNamespace(raw=b"{}", data=SimpleNamespace(**payload))

    def get_facilities(self) -> SimpleNamespace:
        return self._empty("facility", facilities=[])

    def get_fridges(self) -> SimpleNamespace:
        return self._empty("fridge", fridges=[])

    def get_product_types(self) -> SimpleNamespace:
        return self._empty("producttype", productTypes=[])

    def get_fridge_product_prices(self) -> SimpleNamespace:
        return self._empty("fridgeproductprice", fridges=[])

    def get_purchases(self, *window: object) -> SimpleNamespace:
        return self._empty("purchases", fridges={})

    def get_restock(self, *window: object) -> SimpleNamespace:
        return self._empty("restock", sessions={})

    def get_product_reviews(self, *window: object) -> SimpleNamespace:
        return self._empty("productreview", productReviews=[])

    def get_stock_current(self) -> SimpleNamespace:
        return self._empty("stock_current", current=[])


@pytest.mark.parametrize(
    "sync_job, expected_endpoints",
    [
        (sync_catalogue, ["facility", "fridge", "producttype", "fridgeproductprice"]),
        (sync_prices, ["fridgeproductprice"]),
        (sync_purchases_window, ["purchases"]),
        (sync_restock_window, ["restock"]),
        (sync_reviews_window, ["productreview"]),
        (snapshot_stock, ["stock_current"]),
    ],
)
def test_sync_fetches_before_opening_a_db_transaction(
    ctx,
    monkeypatch,
    sync_job,
    expected_endpoints,
) -> None:
    connection = ctx.session.get_bind()
    open_sessions: list[Session] = []

    def _tracked_session() -> Session:
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        open_sessions.append(session)
        return session

    job_steps: list[str] = []
    real_write_transaction = husky_sync.write_transaction

    def _record_archive(endpoint: str, *args: object) -> str:
        job_steps.append(f"archive {endpoint}")
        return "raw/husky/test.json.gz"

    @contextmanager
    def _record_write_transaction(job: str):
        job_steps.append("write transaction")
        with real_write_transaction(job) as session:
            yield session

    monkeypatch.setattr(husky_sync, "SessionLocal", _tracked_session)
    monkeypatch.setattr(husky_sync, "HuskyClient", _EmptyHuskyClient)
    monkeypatch.setattr(husky_sync, "archive_raw", _record_archive)
    monkeypatch.setattr(husky_sync, "write_transaction", _record_write_transaction)
    monkeypatch.setattr(_EmptyHuskyClient, "open_sessions", open_sessions)
    monkeypatch.setattr(_EmptyHuskyClient, "endpoints_called", [])

    sync_job()

    assert _EmptyHuskyClient.endpoints_called == expected_endpoints
    archive_steps = [f"archive {endpoint}" for endpoint in expected_endpoints]
    assert job_steps == [*archive_steps, "write transaction"]


# ===========================================================================
# COPY round trip keeps awkward text, NULLs and timestamp arrays intact
# ===========================================================================


def test_copy_upsert_round_trips_quotes_newlines_empty_strings_and_nulls(ctx) -> None:
    session = ctx.session
    code = f"{TAG}COPY-001"
    _seed_stock_products(session, [code])
    ref = f"{TAG}copy-ref"
    awkward_text = 'He said "great", then\nleft; back\\slash'
    _upsert_reviews(
        session,
        [
            {
                "husky_ref": ref,
                "product_id": _product_id(session, code),
                "fridge_id": None,
                "rating": 1,
                "reviewed_at": datetime.datetime(2026, 6, 1, 12, tzinfo=datetime.timezone.utc),
                "review_text": awkward_text,
                "reviewer_email": "",
                "purchase_id": None,
                "purchased_at": None,
                "review_category": None,
                "tag_id": None,
                "epc": None,
                "product_reference": None,
            }
        ],
    )
    row = session.execute(
        text(
            "SELECT review_text, reviewer_email, purchase_id, reviewed_at "
            "FROM product_reviews WHERE husky_ref = :r"
        ),
        {"r": ref},
    ).one()
    assert row.review_text == awkward_text
    assert row.reviewer_email == ""
    assert row.purchase_id is None
    assert row.reviewed_at == datetime.datetime(2026, 6, 1, 12, tzinfo=datetime.timezone.utc)


def test_snapshot_stock_stores_tag_expiry_dates(ctx, monkeypatch) -> None:
    session = ctx.session
    code = f"{TAG}SC-EXP"
    _seed_stock_products(session, [code])
    fridge = _seed_stock_fridge(session, "expiry")
    first_expiry = datetime.datetime(2026, 11, 2, 23, 0, tzinfo=datetime.timezone.utc)
    second_expiry = datetime.datetime(2026, 11, 4, 23, 0, tzinfo=datetime.timezone.utc)
    stocked_product = SimpleNamespace(
        productCode=code,
        current=[
            SimpleNamespace(expiryDate=first_expiry),
            SimpleNamespace(expiryDate=None),
            SimpleNamespace(expiryDate=second_expiry),
        ],
    )
    payload = SimpleNamespace(
        raw=b"{}",
        data=SimpleNamespace(
            current=[
                SimpleNamespace(
                    fridge=SimpleNamespace(name=fridge.husky_id, friendlyName=None),
                    products=[stocked_product],
                )
            ]
        ),
    )
    _stock_snapshot_env(ctx, monkeypatch, payload)
    snapshot_stock()

    row = session.execute(
        text("SELECT units, expiry_dates FROM fridge_stock WHERE fridge_id = :f"),
        {"f": fridge.id},
    ).one()
    assert row.units == 3
    assert row.expiry_dates == [first_expiry, second_expiry]


def test_snapshot_stock_sweeps_a_reported_fridge_that_is_now_empty(ctx, monkeypatch) -> None:
    session = ctx.session
    code_a = f"{TAG}SC-EMPTY"
    _seed_stock_products(session, [code_a])
    fridge = _seed_stock_fridge(session, "emptied")

    _stock_snapshot_env(
        ctx, monkeypatch, _fake_stock_payload({fridge.husky_id: {code_a: 2}})
    )
    snapshot_stock()
    assert _fridge_stock_rows(session, fridge.id)[code_a][0] == 2

    # Husky reports the fridge with no products at all: it was emptied, so its
    # old rows must go, or allocation would keep reading 2 units that are gone.
    _stock_snapshot_env(ctx, monkeypatch, _fake_stock_payload({fridge.husky_id: {}}))
    outcome = snapshot_stock()

    assert outcome.upserted == 0
    assert _fridge_stock_rows(session, fridge.id) == {}
    assert any("swept=1 fridges_reported=1" in note for note in outcome.notes), outcome.notes


# ===========================================================================
# Pure: COPY text rendering
# ===========================================================================


@pytest.mark.parametrize(
    "value, expected_text",
    [
        (None, None),
        (True, "True"),
        (False, "False"),
        (Decimal("0.0600"), "0.0600"),
        (42, "42"),
        ("", ""),
        (
            datetime.datetime(2026, 6, 1, 12, tzinfo=datetime.timezone.utc),
            "2026-06-01T12:00:00+00:00",
        ),
        ([], "{}"),
        (
            [datetime.datetime(2026, 6, 1, 12, tzinfo=datetime.timezone.utc), None],
            '{"2026-06-01T12:00:00+00:00",NULL}',
        ),
        (['say "hi"', "back\\slash"], '{"say \\"hi\\"","back\\\\slash"}'),
    ],
)
def test_copy_text_renders_postgres_input(value, expected_text) -> None:
    assert _copy_text(value) == expected_text
