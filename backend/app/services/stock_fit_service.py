"""Fit planned fridge x product quantities to the warehouse stock ("Fit to stock").

By default only PHYSICAL warehouse stock counts (``v_stock_balances.physical_qty``).
With "Include ordered", the open remainder of pending purchase orders due on or
before the delivery date counts too (closed_short and cancelled orders are never
on order). When the fridges together ask for more of a product than is
available, each fridge is cut in proportion to what it asked for (largest
remainder, so the cut quantities sum exactly to the stock). The cut units stay
unallocated. The DB trigger that keeps stock >= 0 is still the last guard when a
dispatch is created, so ordered units must be received before that.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import PoStatus
from app.services.replenishment_service import split_by_weight

PHYSICAL_STOCK_SQL = text(
    "SELECT product_id, physical_qty FROM v_stock_balances WHERE product_id = ANY(:ids)"
)
ORDERED_STOCK_SQL = text(
    """
    SELECT pol.product_id,
           SUM(GREATEST(pol.qty_ordered - pol.qty_received, 0)) AS ordered_qty
      FROM purchase_order_lines pol
      JOIN purchase_orders po ON po.id = pol.po_id
     WHERE po.status = :pending
       AND po.expected_delivery_date <= :due_by
       AND pol.product_id = ANY(:ids)
     GROUP BY pol.product_id
    """
)
NO_ORDERED_STOCK: Mapping[int, int] = MappingProxyType({})


@dataclass(frozen=True)
class StockFitLine:
    fridge_id: int
    product_id: int
    qty: int


@dataclass(frozen=True)
class ProductStockCut:
    """A product the fridges asked more of than the warehouse holds."""

    product_id: int
    requested: int
    in_stock: int
    cut: int
    # Part of ``in_stock`` that is still on a purchase order (0 unless orders are included).
    on_order: int = 0


@dataclass(frozen=True)
class ProductOrderUse:
    """Units of a product that only fit because a purchase order is due in time."""

    product_id: int
    units_from_orders: int


@dataclass(frozen=True)
class StockFit:
    # Same lines, same order, with the quantities cut to stock (a line can drop to 0).
    lines: list[StockFitLine]
    cuts: list[ProductStockCut]
    order_uses: list[ProductOrderUse]


def fit_lines_to_warehouse_stock(
    lines: list[StockFitLine],
    session: Session,
    include_orders_due_by: datetime.date | None = None,
) -> StockFit:
    """Cut ``lines`` to the physical warehouse stock, plus orders due by the given date if set."""
    if not lines:
        return StockFit(lines=[], cuts=[], order_uses=[])
    product_ids = sorted({line.product_id for line in lines})
    stock_rows = session.execute(PHYSICAL_STOCK_SQL, {"ids": product_ids}).all()
    physical_stock = {row.product_id: int(row.physical_qty) for row in stock_rows}
    ordered_stock = NO_ORDERED_STOCK
    if include_orders_due_by is not None:
        ordered_stock = _load_ordered_stock(product_ids, include_orders_due_by, session)
    return fit_lines_to_stock(lines, physical_stock, ordered_stock)


def fit_lines_to_stock(
    lines: list[StockFitLine],
    physical_stock: Mapping[int, int],
    ordered_stock: Mapping[int, int] = NO_ORDERED_STOCK,
) -> StockFit:
    """Cut each over-asked product proportionally per fridge; other lines stay as they are."""
    line_positions_by_product: dict[int, list[int]] = {}
    for position, line in enumerate(lines):
        line_positions_by_product.setdefault(line.product_id, []).append(position)

    fitted_quantities = [line.qty for line in lines]
    cuts: list[ProductStockCut] = []
    order_uses: list[ProductOrderUse] = []
    for product_id, positions in line_positions_by_product.items():
        requested_quantities = [lines[position].qty for position in positions]
        requested = sum(requested_quantities)
        # A negative balance cannot be taken from, so it counts as an empty shelf.
        on_shelf = max(physical_stock.get(product_id, 0), 0)
        on_order = ordered_stock.get(product_id, 0)
        in_stock = on_shelf + on_order
        units_from_orders = min(requested, in_stock) - on_shelf
        if units_from_orders > 0:
            order_uses.append(
                ProductOrderUse(product_id=product_id, units_from_orders=units_from_orders)
            )
        if requested <= in_stock:
            continue
        request_weights = [Decimal(qty) for qty in requested_quantities]
        fitted_shares = split_by_weight(in_stock, request_weights)
        for position, fitted_qty in zip(positions, fitted_shares):
            fitted_quantities[position] = fitted_qty
        cuts.append(
            ProductStockCut(
                product_id=product_id,
                requested=requested,
                in_stock=in_stock,
                cut=requested - in_stock,
                on_order=on_order,
            )
        )

    fitted_lines = [
        StockFitLine(fridge_id=line.fridge_id, product_id=line.product_id, qty=fitted_qty)
        for line, fitted_qty in zip(lines, fitted_quantities)
    ]
    return StockFit(lines=fitted_lines, cuts=cuts, order_uses=order_uses)


def _load_ordered_stock(
    product_ids: list[int],
    due_by: datetime.date,
    session: Session,
) -> dict[int, int]:
    ordered_rows = session.execute(
        ORDERED_STOCK_SQL,
        {
            "pending": PoStatus.pending.value,
            "due_by": due_by,
            "ids": product_ids,
        },
    ).all()
    return {row.product_id: int(row.ordered_qty) for row in ordered_rows}
