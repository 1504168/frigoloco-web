"""Low-stock alerts: one alert per product whose warehouse stock is below its minimum."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import column, select, table
from sqlalchemy.orm import Session

from app.husky.sync import EFFECTIVE_STATUS_ACTIVE, effective_status_clause
from app.models.enums import AlertType
from app.models.master import Product
from app.models.operations import Alert
from app.schemas.masters import api_error
from app.services.stock_service import record_audit

RESOLVED_STATUS = "resolved"

# Warehouse stock per product (physical_qty = sum of stock movements).
STOCK_BALANCES_VIEW = table(
    "v_stock_balances",
    column("product_id"),
    column("physical_qty"),
    column("on_order_qty"),
)


@dataclass(frozen=True)
class LowStockProduct:
    product_id: int
    product_code: str
    product_name: str
    physical_qty: int
    on_order_qty: int
    min_stock_qty: int


@dataclass(frozen=True)
class MinimumStockUpdate:
    product_id: int
    min_stock_qty: int | None
    physical_qty: int
    is_low_stock: bool


@dataclass
class LowStockRefreshOutcome:
    """How many low_stock alerts one refresh opened, refreshed and resolved."""

    opened: int = 0
    updated: int = 0
    resolved: int = 0


def is_below_minimum_stock(physical_qty: int, min_stock_qty: int | None) -> bool:
    """True when a minimum is set and the warehouse holds fewer units than it."""
    return min_stock_qty is not None and physical_qty < min_stock_qty


def set_minimum_stock(
    *,
    product_id: int,
    min_stock_qty: int | None,
    user_id: int,
    session: Session,
) -> MinimumStockUpdate:
    """Save a product's warehouse minimum and bring the low_stock alerts up to date now."""
    product = session.get(Product, product_id)
    if product is None:
        raise api_error(404, "not_found", "Product not found", {"product_id": product_id})
    record_audit(
        session,
        action="product.min_stock_qty",
        entity="products",
        entity_id=product_id,
        before={"min_stock_qty": product.min_stock_qty},
        after={"min_stock_qty": min_stock_qty},
        user_id=user_id,
    )
    product.min_stock_qty = min_stock_qty
    session.flush()
    refresh_low_stock_alerts(session)
    physical_qty = session.execute(
        select(STOCK_BALANCES_VIEW.c.physical_qty).where(
            STOCK_BALANCES_VIEW.c.product_id == product_id
        )
    ).scalar_one()
    session.commit()
    return MinimumStockUpdate(
        product_id=product_id,
        min_stock_qty=min_stock_qty,
        physical_qty=int(physical_qty),
        is_low_stock=is_below_minimum_stock(int(physical_qty), min_stock_qty),
    )


def refresh_low_stock_alerts(session: Session) -> LowStockRefreshOutcome:
    """Open or refresh one low_stock alert per low product; resolve the recovered ones.

    An acknowledged alert still counts as the product's alert, so a product that
    stays low is never alerted twice. The caller commits.
    """
    low_stock_products = _load_low_stock_products(session)
    unresolved_alerts_by_product = _load_unresolved_alerts_by_product(session)
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    outcome = LowStockRefreshOutcome()

    for product in low_stock_products:
        payload = _build_alert_payload(product, checked_at)
        existing_alert = unresolved_alerts_by_product.pop(product.product_id, None)
        if existing_alert is None:
            session.add(Alert(alert_type=AlertType.low_stock, payload=payload))
            outcome.opened += 1
        else:
            existing_alert.payload = payload
            outcome.updated += 1

    recovered_alerts = unresolved_alerts_by_product.values()
    for alert in recovered_alerts:
        alert.status = RESOLVED_STATUS
        outcome.resolved += 1
    session.flush()
    return outcome


def _load_low_stock_products(session: Session) -> list[LowStockProduct]:
    physical_qty = STOCK_BALANCES_VIEW.c.physical_qty
    low_stock_query = (
        select(
            Product.id,
            Product.code,
            Product.name,
            physical_qty,
            STOCK_BALANCES_VIEW.c.on_order_qty,
            Product.min_stock_qty,
        )
        .join(STOCK_BALANCES_VIEW, STOCK_BALANCES_VIEW.c.product_id == Product.id)
        .where(
            Product.min_stock_qty.is_not(None),
            physical_qty < Product.min_stock_qty,
            effective_status_clause(Product, EFFECTIVE_STATUS_ACTIVE),
        )
        .order_by(Product.id)
    )
    low_stock_products = []
    for row in session.execute(low_stock_query):
        low_stock_products.append(
            LowStockProduct(
                product_id=row.id,
                product_code=row.code,
                product_name=row.name,
                physical_qty=int(row.physical_qty),
                on_order_qty=int(row.on_order_qty),
                min_stock_qty=row.min_stock_qty,
            )
        )
    return low_stock_products


def _load_unresolved_alerts_by_product(session: Session) -> dict[int, Alert]:
    unresolved_alerts = session.execute(
        select(Alert)
        .where(
            Alert.alert_type == AlertType.low_stock,
            Alert.status != RESOLVED_STATUS,
        )
        .with_for_update()
    ).scalars()
    return {alert.payload["product_id"]: alert for alert in unresolved_alerts}


def _build_alert_payload(product: LowStockProduct, checked_at: str) -> dict:
    message = (
        f"Low warehouse stock: {product.product_name} ({product.product_code}) has "
        f"{product.physical_qty} in the warehouse, below the minimum of "
        f"{product.min_stock_qty}. {product.on_order_qty} on order."
    )
    return {
        "message": message,
        "product_id": product.product_id,
        "product_code": product.product_code,
        "physical_qty": product.physical_qty,
        "on_order_qty": product.on_order_qty,
        "min_stock_qty": product.min_stock_qty,
        "last_checked_at": checked_at,
    }
