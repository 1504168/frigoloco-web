"""Where one product is right now: units per fridge (``fridge_stock``) plus the warehouse.

Fridge units come from the latest Husky ``/stock/current`` reading that the
``snapshot_stock`` job writes every 15 min. A fridge the job could not reach keeps
its last rows with their old ``taken_at``, so each fridge is flagged stale on its own.
"""

from __future__ import annotations

import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.husky.sync import EFFECTIVE_STATUS_ACTIVE, effective_status, utcnow
from app.models.master import Fridge, Product
from app.models.sync import FridgeStock
from app.schemas.masters import api_error
from app.schemas.stock import FridgeUnitsOut, ProductLocationsOut, SameNameProductOut
from app.services.menu_allocation_service import STOCK_READING_MAX_AGE

_WAREHOUSE_BALANCE_SQL = text(
    "SELECT product_id, product_code, product_name, physical_qty, on_order_qty, available_qty "
    "FROM v_stock_balances WHERE product_id = :product_id"
)


def get_product_locations(product_id: int, session: Session) -> ProductLocationsOut:
    """Units of ``product_id`` in every fridge holding it, plus its warehouse balance."""
    warehouse = session.execute(
        _WAREHOUSE_BALANCE_SQL,
        {"product_id": product_id},
    ).one_or_none()
    if warehouse is None:
        raise api_error(404, "not_found", "Product not found", {"product_id": product_id})

    fridges = _list_fridge_units(product_id, session)
    fridge_units_total = sum(fridge.units for fridge in fridges)
    # Across all fridges, so a product held by none still shows when stock was last read.
    latest_taken_at = session.scalar(select(func.max(FridgeStock.taken_at)))
    product = session.get(Product, product_id)
    return ProductLocationsOut(
        product_id=warehouse.product_id,
        product_code=warehouse.product_code,
        product_name=warehouse.product_name,
        physical_qty=warehouse.physical_qty,
        on_order_qty=warehouse.on_order_qty,
        available_qty=warehouse.available_qty,
        fridge_units_total=fridge_units_total,
        latest_taken_at=latest_taken_at,
        fridges=fridges,
        is_active=_is_active(product.local_status, product.is_active),
        same_name_products=_list_same_name_products(product, session),
    )


def _list_fridge_units(product_id: int, session: Session) -> list[FridgeUnitsOut]:
    rows = session.execute(
        select(
            Fridge.id,
            Fridge.friendly_name,
            FridgeStock.units,
            FridgeStock.expiry_dates,
            FridgeStock.taken_at,
        )
        .join(Fridge, Fridge.id == FridgeStock.fridge_id)
        .where(
            FridgeStock.product_id == product_id,
            FridgeStock.units > 0,
        )
        .order_by(FridgeStock.units.desc(), Fridge.friendly_name)
    ).all()

    stale_before = utcnow() - STOCK_READING_MAX_AGE
    fridges: list[FridgeUnitsOut] = []
    for row in rows:
        fridges.append(
            FridgeUnitsOut(
                fridge_id=row.id,
                fridge_name=row.friendly_name,
                units=row.units,
                next_expiry_at=_earliest_expiry(row.expiry_dates),
                taken_at=row.taken_at,
                is_stale=row.taken_at < stale_before,
            )
        )
    return fridges


def _is_active(local_status: str | None, is_active: bool) -> bool:
    return effective_status(local_status, is_active) == EFFECTIVE_STATUS_ACTIVE


def _list_same_name_products(product: Product, session: Session) -> list[SameNameProductOut]:
    """Other products sharing this name, so a user on an old code finds the live one."""
    fridge_units = func.coalesce(func.sum(FridgeStock.units), 0)
    rows = session.execute(
        select(
            Product.id,
            Product.code,
            Product.local_status,
            Product.is_active,
            fridge_units.label("fridge_units"),
        )
        .outerjoin(FridgeStock, FridgeStock.product_id == Product.id)
        .where(
            func.lower(func.trim(Product.name)) == product.name.strip().lower(),
            Product.id != product.id,
        )
        .group_by(Product.id)
        .order_by(fridge_units.desc(), Product.code)
    ).all()
    same_name_products: list[SameNameProductOut] = []
    for row in rows:
        same_name_products.append(
            SameNameProductOut(
                product_id=row.id,
                product_code=row.code,
                is_active=_is_active(row.local_status, row.is_active),
                fridge_units=int(row.fridge_units),
            )
        )
    return same_name_products


def _earliest_expiry(
    expiry_dates: list[datetime.datetime] | None,
) -> datetime.datetime | None:
    if not expiry_dates:
        return None
    return min(expiry_dates)
