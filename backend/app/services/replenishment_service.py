"""Split a fridge x category forecast quantity over the week menu's products.

The plain split follows product rating. Sold-first (spec 0008) first refills the
products sold in the fridge since the category's last delivery there, then
splits what is left by rating. The stock-aware cut (spec 0009) then delivers only
what each product's share needs beyond its good units already in the fridge.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

LOCAL_TIMEZONE = ZoneInfo("Europe/Brussels")
# A category not delivered to a fridge for this long restarts from a plain rating split.
SOLD_FIRST_LOOKBACK = datetime.timedelta(days=14)
ZERO_WEIGHT = Decimal("0")

# Last delivery = newest Husky restock ADDED event of any product of the category
# in the fridge, so a snack top-up never resets the dessert window.
LAST_DELIVERY_CTE = """
    WITH last_delivery AS (
        SELECT restock.fridge_id,
               product.category_id,
               max(restock.occurred_at) AS delivered_at
        FROM restock_events AS restock
        JOIN products AS product ON product.id = restock.product_id
        WHERE restock.action = 'added'
          AND restock.tag_status = 'valid'
          AND restock.fridge_id = ANY(:fridge_ids)
          AND product.category_id = ANY(:category_ids)
          AND restock.occurred_at >= :lookback_start
          AND restock.occurred_at < :delivery_start
        GROUP BY restock.fridge_id, product.category_id
    )
"""
SALES_SINCE_LAST_DELIVERY_SQL = text(
    LAST_DELIVERY_CTE
    + """
    SELECT sale.fridge_id,
           sale.product_id,
           count(*) AS sold_qty
    FROM sales_events AS sale
    JOIN products AS product ON product.id = sale.product_id
    JOIN last_delivery
      ON last_delivery.fridge_id = sale.fridge_id
     AND last_delivery.category_id = product.category_id
    WHERE sale.product_id = ANY(:product_ids)
      AND NOT sale.is_refunded
      AND sale.sold_at >= :lookback_start
      AND sale.sold_at > last_delivery.delivered_at
      AND sale.sold_at < :delivery_start
    GROUP BY sale.fridge_id, sale.product_id
    """
)
CATEGORY_SALES_SINCE_LAST_DELIVERY_SQL = text(
    LAST_DELIVERY_CTE
    + """
    SELECT last_delivery.fridge_id,
           last_delivery.category_id,
           last_delivery.delivered_at,
           count(sale.product_id) AS sold_qty
    FROM last_delivery
    JOIN products AS product ON product.category_id = last_delivery.category_id
    LEFT JOIN sales_events AS sale
      ON sale.fridge_id = last_delivery.fridge_id
     AND sale.product_id = product.id
     AND NOT sale.is_refunded
     AND sale.sold_at >= :lookback_start
     AND sale.sold_at > last_delivery.delivered_at
     AND sale.sold_at < :delivery_start
    GROUP BY last_delivery.fridge_id, last_delivery.category_id, last_delivery.delivered_at
    """
)


@dataclass(frozen=True)
class StockCutQuantity:
    """One product's delivery after the fridge-stock cut, with what explains it."""

    qty: int
    in_fridge_units: int
    reduced_by: int


@dataclass(frozen=True)
class CategorySalesSinceDelivery:
    """Units of a category sold in a fridge since its last delivery there."""

    fridge_id: int
    category_id: int
    delivered_at: datetime.datetime
    sold_qty: int


def split_by_weight(target: int, weights: list[Decimal]) -> list[int]:
    """Distribute ``target`` integer units across ``weights`` proportionally.

    Largest-remainder method: leftover units after flooring go to the highest
    fractional remainders (ties broken by weight), so the result sums to ``target``.
    """
    total = sum(weights, ZERO_WEIGHT)
    if target <= 0 or total <= 0:
        return [0] * len(weights)
    exact = [Decimal(target) * weight / total for weight in weights]
    floors = [int(value) for value in exact]
    leftover = target - sum(floors)

    def remainder_then_weight(index: int) -> tuple[Decimal, Decimal]:
        return exact[index] - floors[index], weights[index]

    order = sorted(range(len(weights)), key=remainder_then_weight, reverse=True)
    for step in range(leftover):
        floors[order[step % len(order)]] += 1
    return floors


def split_category_quantity(
    *,
    target: int,
    weights: list[Decimal],
    sold_quantities: list[int],
) -> list[int]:
    """Per-product quantities for one fridge x category, in the order of ``weights``.

    Each product first gets what it sold since the last delivery; the rest of
    ``target`` is split by weight over the products that sold nothing (over all of
    them when every product sold). Sales above ``target`` are scaled down to it in
    proportion to the sales. All-zero ``sold_quantities`` is the plain weight split.
    """
    total_sold = sum(sold_quantities)
    if total_sold >= target:
        sold_weights = [Decimal(sold_qty) for sold_qty in sold_quantities]
        return split_by_weight(target, sold_weights)

    remainder_weights = _weights_of_unsold_products(weights, sold_quantities)
    remainder = split_by_weight(target - total_sold, remainder_weights)
    return [
        sold_qty + remainder_qty
        for sold_qty, remainder_qty in zip(sold_quantities, remainder)
    ]


def cut_by_fridge_stock(
    *,
    shares: list[int],
    good_units: list[int],
) -> list[StockCutQuantity]:
    """Each product gets its share minus its good in-fridge units; a well-stocked one gets 0."""
    cut_quantities: list[StockCutQuantity] = []
    for share, in_fridge_units in zip(shares, good_units):
        qty = max(share - in_fridge_units, 0)
        cut_quantities.append(
            StockCutQuantity(
                qty=qty,
                in_fridge_units=in_fridge_units,
                reduced_by=share - qty,
            )
        )
    return cut_quantities


def load_sales_since_last_delivery(
    *,
    fridge_ids: list[int],
    category_ids: list[int],
    product_ids: list[int],
    delivery_date: datetime.date,
    session: Session,
) -> dict[int, dict[int, int]]:
    """Units sold per fridge -> product since that category's last delivery to the fridge.

    Only sales before the delivery day count. A (fridge, category) with no delivery
    in :data:`SOLD_FIRST_LOOKBACK` has no entry, so it gets the plain rating split.
    """
    rows = session.execute(
        SALES_SINCE_LAST_DELIVERY_SQL,
        {
            "fridge_ids": fridge_ids,
            "category_ids": category_ids,
            "product_ids": product_ids,
            **_last_delivery_window(delivery_date),
        },
    ).all()
    sold_by_fridge: dict[int, dict[int, int]] = {}
    for row in rows:
        sold_by_fridge.setdefault(row.fridge_id, {})[row.product_id] = int(row.sold_qty)
    return sold_by_fridge


def load_category_sales_since_last_delivery(
    *,
    fridge_ids: list[int],
    category_ids: list[int],
    delivery_date: datetime.date,
    session: Session,
) -> list[CategorySalesSinceDelivery]:
    """Each (fridge, category) delivered in the lookback, with its sales since (any product)."""
    rows = session.execute(
        CATEGORY_SALES_SINCE_LAST_DELIVERY_SQL,
        {
            "fridge_ids": fridge_ids,
            "category_ids": category_ids,
            **_last_delivery_window(delivery_date),
        },
    ).all()
    return [
        CategorySalesSinceDelivery(
            fridge_id=row.fridge_id,
            category_id=row.category_id,
            delivered_at=row.delivered_at,
            sold_qty=int(row.sold_qty),
        )
        for row in rows
    ]


def delivery_start(delivery_date: datetime.date) -> datetime.datetime:
    """Local midnight of the delivery day: sales from then on belong to the new delivery."""
    return datetime.datetime.combine(
        delivery_date,
        datetime.time.min,
        tzinfo=LOCAL_TIMEZONE,
    )


def _last_delivery_window(delivery_date: datetime.date) -> dict[str, datetime.datetime]:
    """Query bounds: a last delivery within the lookback, sales before the delivery day."""
    window_end = delivery_start(delivery_date)
    return {
        "lookback_start": window_end - SOLD_FIRST_LOOKBACK,
        "delivery_start": window_end,
    }


def _weights_of_unsold_products(
    weights: list[Decimal],
    sold_quantities: list[int],
) -> list[Decimal]:
    """Weights of products that sold nothing; all weights when those sum to zero."""
    unsold_weights = [
        ZERO_WEIGHT if sold_qty > 0 else weight
        for weight, sold_qty in zip(weights, sold_quantities)
    ]
    if sum(unsold_weights, ZERO_WEIGHT) <= 0:
        return weights
    return unsold_weights
