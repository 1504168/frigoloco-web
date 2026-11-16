"""Pure tests (no DB, no network) for the Husky-not-configured guard, the fridge
ownership contract, and the low-stock rule."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.husky.sync import (
    FRIDGE_HUSKY_OWNED,
    FRIDGE_LOCAL_OWNED,
    HUSKY_NOT_CONFIGURED_MESSAGE,
    PRODUCT_LOCAL_OWNED,
    SyncContractError,
    _guarded_update_set,
)
from app.main import app
from app.routers import husky_sync as sync_router
from app.routers import stock as stock_router
from app.services.low_stock_service import is_below_minimum_stock

PREFIX = "/api/v1"


def test_sync_trigger_returns_503_before_creating_a_run(monkeypatch) -> None:
    created_runs: list[tuple] = []
    monkeypatch.setattr(sync_router, "is_husky_configured", lambda: False)
    monkeypatch.setattr(
        sync_router,
        "create_sync_run",
        lambda *args, **kwargs: created_runs.append(args),
    )

    response = TestClient(app).post(f"{PREFIX}/sync/husky/catalogue")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == HUSKY_NOT_CONFIGURED_MESSAGE
    assert created_runs == []


def test_live_stock_refresh_returns_503_when_husky_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(stock_router, "is_husky_configured", lambda: False)

    response = TestClient(app).post(f"{PREFIX}/stock/products/1/fridges/refresh")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "husky_not_configured"


def test_husky_status_is_husky_owned_and_preferences_local() -> None:
    assert "husky_status" in FRIDGE_HUSKY_OWNED
    assert "preferences" in FRIDGE_LOCAL_OWNED
    with pytest.raises(SyncContractError):
        _guarded_update_set("fridges", {"preferences": "no pork"})


def test_product_minimum_and_print_order_are_never_written_by_sync() -> None:
    assert "min_stock_qty" in PRODUCT_LOCAL_OWNED
    assert "print_order" in PRODUCT_LOCAL_OWNED
    with pytest.raises(SyncContractError):
        _guarded_update_set("products", {"min_stock_qty": 5})


@pytest.mark.parametrize(
    "physical_qty, min_stock_qty, expected",
    [
        (3, 10, True),
        (10, 10, False),
        (12, 10, False),
        (0, None, False),
        (-2, 0, True),
    ],
)
def test_is_below_minimum_stock(physical_qty, min_stock_qty, expected) -> None:
    assert is_below_minimum_stock(physical_qty, min_stock_qty) is expected
