"""Product locations: units per fridge from fridge_stock plus the warehouse balance."""

from __future__ import annotations

import datetime

import httpx
from sqlalchemy import text

from app.husky.sync import utcnow
from app.routers import stock as stock_router
from tests.test_ops_routers import (
    PREFIX,
    TAG,
    _category_ids,
    _create_fridge,
    _create_product,
    ctx,  # noqa: F401 - pytest fixture
)

STALE_READING_AGE = datetime.timedelta(hours=3)
MISSING_PRODUCT_ID = 999_999_999


def _locations_url(product_id: int) -> str:
    return f"{PREFIX}/stock/products/{product_id}/fridges"


def _seed_fridge_stock(
    ctx,  # noqa: F811
    *,
    fridge_id: int,
    product_id: int,
    units: int,
    taken_at: datetime.datetime,
    expiry_dates: list[datetime.datetime] | None = None,
) -> None:
    ctx.session.execute(
        text(
            "INSERT INTO fridge_stock "
            "(fridge_id, product_code, product_id, units, expiry_dates, taken_at) "
            "SELECT :fridge, code, id, :units, :expiry, :taken_at FROM products WHERE id = :product"
        ),
        {
            "fridge": fridge_id,
            "product": product_id,
            "units": units,
            "expiry": expiry_dates,
            "taken_at": taken_at,
        },
    )
    ctx.session.flush()


def test_locations_list_fridges_holding_the_product_with_staleness(ctx):  # noqa: F811
    product_id = _create_product(
        ctx.client,
        code=f"{TAG}LOC-1",
        category_id=_category_ids(ctx.session)["normal"],
    )
    fresh_fridge = _create_fridge(ctx.client, f"{TAG}loc-fresh")
    stale_fridge = _create_fridge(ctx.client, f"{TAG}loc-stale")
    empty_fridge = _create_fridge(ctx.client, f"{TAG}loc-empty")
    now = utcnow()
    soon = now + datetime.timedelta(days=2)
    later = now + datetime.timedelta(days=5)
    _seed_fridge_stock(
        ctx,
        fridge_id=fresh_fridge,
        product_id=product_id,
        units=2,
        taken_at=now,
        expiry_dates=[later, soon],
    )
    _seed_fridge_stock(
        ctx,
        fridge_id=stale_fridge,
        product_id=product_id,
        units=5,
        taken_at=now - STALE_READING_AGE,
    )
    _seed_fridge_stock(
        ctx,
        fridge_id=empty_fridge,
        product_id=product_id,
        units=0,
        taken_at=now,
    )

    response = ctx.client.get(_locations_url(product_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product_code"] == f"{TAG}LOC-1"
    assert body["physical_qty"] == 0
    assert body["fridge_units_total"] == 7
    fridges = [
        (fridge["fridge_id"], fridge["units"], fridge["is_stale"])
        for fridge in body["fridges"]
    ]
    assert fridges == [
        (stale_fridge, 5, True),
        (fresh_fridge, 2, False),
    ]
    fresh_entry = body["fridges"][1]
    assert datetime.datetime.fromisoformat(fresh_entry["next_expiry_at"]) == soon
    assert datetime.datetime.fromisoformat(body["latest_taken_at"]) == now


def test_locations_without_fridge_stock_still_report_latest_reading(ctx):  # noqa: F811
    category_id = _category_ids(ctx.session)["normal"]
    product_id = _create_product(ctx.client, code=f"{TAG}LOC-2", category_id=category_id)
    other_product_id = _create_product(
        ctx.client,
        code=f"{TAG}LOC-2B",
        category_id=category_id,
    )
    other_fridge = _create_fridge(ctx.client, f"{TAG}loc-other")
    _seed_fridge_stock(
        ctx,
        fridge_id=other_fridge,
        product_id=other_product_id,
        units=3,
        taken_at=utcnow(),
    )
    newest_reading = ctx.session.scalar(text("SELECT max(taken_at) FROM fridge_stock"))

    body = ctx.client.get(_locations_url(product_id)).json()

    assert body["fridges"] == []
    assert body["fridge_units_total"] == 0
    assert datetime.datetime.fromisoformat(body["latest_taken_at"]) == newest_reading


def test_locations_unknown_product_is_404(ctx):  # noqa: F811
    response = ctx.client.get(_locations_url(MISSING_PRODUCT_ID))

    assert response.status_code == 404


def test_refresh_runs_live_snapshot_then_reads(ctx, monkeypatch):  # noqa: F811
    product_id = _create_product(
        ctx.client,
        code=f"{TAG}LOC-3",
        category_id=_category_ids(ctx.session)["normal"],
    )
    fridge_id = _create_fridge(ctx.client, f"{TAG}loc-live")

    def fake_snapshot_stock() -> None:
        _seed_fridge_stock(
            ctx,
            fridge_id=fridge_id,
            product_id=product_id,
            units=4,
            taken_at=utcnow(),
        )

    monkeypatch.setattr(stock_router, "snapshot_stock", fake_snapshot_stock)
    monkeypatch.setattr(stock_router, "is_husky_configured", lambda: True)

    response = ctx.client.post(f"{_locations_url(product_id)}/refresh")

    assert response.status_code == 200, response.text
    assert response.json()["fridge_units_total"] == 4


def test_refresh_reports_husky_outage_as_502(ctx, monkeypatch):  # noqa: F811
    product_id = _create_product(
        ctx.client,
        code=f"{TAG}LOC-4",
        category_id=_category_ids(ctx.session)["normal"],
    )

    def failing_snapshot_stock() -> None:
        raise httpx.ConnectError("Husky unreachable")

    monkeypatch.setattr(stock_router, "snapshot_stock", failing_snapshot_stock)
    monkeypatch.setattr(stock_router, "is_husky_configured", lambda: True)

    response = ctx.client.post(f"{_locations_url(product_id)}/refresh")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "husky_unavailable"
