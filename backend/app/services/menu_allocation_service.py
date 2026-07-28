"""Menu allocation engine - implementation of R3.

Splits each fridge×category forecast across that category's menu products in
proportion to product score:

    alloc_i = round(forecast * score_i / Σ score)

using the largest-remainder method so the per-product integer allocations sum
back to ``round(forecast)`` - leftover units go to the highest-remainder (and, on
ties, highest-scored) product, and any product whose exact share exceeds 0.5 is
rounded up rather than silently dropped. Per-product ``menu_product_caps`` are
respected, with capped overflow redistributed to remaining products.

Snacks & Drinks bypass the score split entirely: their per-product quantity is
``max(target_qty - live_stock, 0)`` from ``product_targets`` and the in-fridge
``fridge_stock`` reading (the latest-known state written by the snapshot job).

Staleness (F7): the snapshot job refreshes ``fridge_stock`` every 15 min and only
sweeps the fridges a payload actually reported on, so each fridge carries its own
generation timestamp. A fridge whose generation is missing or older than
:data:`STOCK_READING_MAX_AGE` was not reached (RFID reader offline, or a partial
vendor response) and its readings are untrustworthy. The forecast still runs on
that fridge's last-known units - quantities are never silently changed - but its
target-replenish lines are flagged ``stock_stale`` so the UI can surface it.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.master import (
    Category,
    MenuProductCap,
    Product,
    ProductTarget,
)
from app.models.planning import (
    ForecastResult,
    MenuProduct,
    ProductScore,
    WeeklyMenu,
)
from app.models.sync import FridgeStock
from app.schemas.masters import api_error

logger = logging.getLogger("services.menu_allocation")

_TARGET_CATEGORY_TOKENS = ("snack", "drink")

SOURCE_FORECAST = "forecast"
SOURCE_TARGET = "target_replenish"

# Beyond this age the whole fridge_stock generation is considered untrustworthy
# (the snapshot job runs every 15 min; the architecture docs specify a 2h bound).
STOCK_READING_MAX_AGE = datetime.timedelta(hours=2)


@dataclass(frozen=True)
class AllocationLine:
    fridge_id: int
    category_id: int
    product_id: int
    qty: int
    source: str
    # True only on target-replenish lines computed from a stale/absent
    # fridge_stock generation. Forecast lines never read stock, so they keep the
    # default.
    stock_stale: bool = False


@dataclass(frozen=True)
class FridgeStockReadings:
    """Latest in-fridge stock per (fridge, product), plus a generation PER FRIDGE.

    The snapshot job sweeps only the fridges a payload reported on, so every
    fridge carries its own generation (``max(taken_at)`` over its rows):

    * fridge reported, product gone   -> its row was swept -> ``live = 0`` against
      a FRESH generation. Correct, and not stale.
    * fridge absent from the payload  -> its rows are retained with their OLD
      generation (RFID reader offline, or a partial vendor response). That old
      timestamp is exactly what flags the fridge stale here.
    * fridge never snapshotted at all -> no generation -> stale.

    Freshness is therefore a property of the fridge's generation, never of an
    individual (fridge, product) key.
    """

    units_by_key: dict[tuple[int, int], int] = field(default_factory=dict)
    taken_at_by_fridge: dict[int, datetime.datetime] = field(default_factory=dict)

    def units(self, fridge_id: int, product_id: int) -> int:
        return self.units_by_key.get((fridge_id, product_id), 0)

    def is_stale(self, fridge_id: int, now: datetime.datetime) -> bool:
        taken_at = self.taken_at_by_fridge.get(fridge_id)
        if taken_at is None:
            return True
        return taken_at < now - STOCK_READING_MAX_AGE

    def stale_fridge_ids(
        self, fridge_ids: list[int], now: datetime.datetime
    ) -> dict[int, bool]:
        """Decide staleness once per fridge, for reuse across that fridge's lines."""
        return {
            fridge_id: self.is_stale(fridge_id, now) for fridge_id in fridge_ids
        }


def _largest_remainder(target: int, weights: list[Decimal]) -> list[int]:
    """Distribute ``target`` integer units across ``weights`` proportionally."""
    total = sum(weights, Decimal("0"))
    if target <= 0 or total <= 0:
        return [0] * len(weights)

    exact = [Decimal(target) * weight / total for weight in weights]
    floors = [int(value) for value in exact]  # Decimal int() truncates toward 0
    leftover = target - sum(floors)

    order = sorted(
        range(len(weights)),
        key=lambda i: (exact[i] - floors[i], weights[i]),
        reverse=True,
    )
    for step in range(leftover):
        floors[order[step % len(order)]] += 1
    return floors


def _apply_caps(
    product_ids: list[int],
    allocations: list[int],
    caps: dict[int, int],
    scores: list[Decimal],
) -> list[int]:
    """Clamp allocations to caps and redistribute overflow by descending score."""
    capped = [
        min(qty, caps[pid]) if pid in caps else qty
        for pid, qty in zip(product_ids, allocations)
    ]
    overflow = sum(allocations) - sum(capped)
    if overflow <= 0:
        return capped

    order = sorted(range(len(product_ids)), key=lambda i: scores[i], reverse=True)
    while overflow > 0:
        progressed = False
        for i in order:
            pid = product_ids[i]
            ceiling = caps.get(pid)
            if ceiling is None or capped[i] < ceiling:
                capped[i] += 1
                overflow -= 1
                progressed = True
                if overflow == 0:
                    break
        if not progressed:  # every product is at its cap
            break
    return capped


def _fridge_stock_readings(
    fridge_ids: list[int], session: Session
) -> FridgeStockReadings:
    """Read the latest in-fridge stock for ``fridge_ids`` plus each one's generation.

    A fridge the snapshot job could not reach is deliberately NOT emptied by the
    job's sweep: it keeps its rows with their last generation timestamp, so the
    staleness check below can flag it instead of silently reading it as empty.
    """
    if not fridge_ids:
        return FridgeStockReadings()
    rows = session.execute(
        select(
            FridgeStock.fridge_id,
            FridgeStock.product_id,
            FridgeStock.units,
            FridgeStock.taken_at,
        ).where(
            FridgeStock.fridge_id.in_(fridge_ids),
            FridgeStock.product_id.is_not(None),
        )
    ).all()

    units_by_key: dict[tuple[int, int], int] = {}
    taken_at_by_fridge: dict[int, datetime.datetime] = {}
    for row in rows:
        units_by_key[(row.fridge_id, row.product_id)] = int(row.units)
        generation = taken_at_by_fridge.get(row.fridge_id)
        if generation is None or row.taken_at > generation:
            taken_at_by_fridge[row.fridge_id] = row.taken_at
    return FridgeStockReadings(
        units_by_key=units_by_key, taken_at_by_fridge=taken_at_by_fridge
    )


def compute_allocation(
    *, menu_id: int, forecast_run_id: int, session: Session
) -> list[AllocationLine]:
    """Compute (do not persist) the allocation lines for a menu + forecast run."""
    menu = session.get(WeeklyMenu, menu_id)
    if menu is None:
        raise api_error(404, "not_found", "Menu not found", {"menu_id": menu_id})

    results = list(
        session.execute(
            select(ForecastResult).where(ForecastResult.run_id == forecast_run_id)
        )
        .scalars()
        .all()
    )
    if not results:
        raise api_error(
            404,
            "not_found",
            "Forecast run has no results",
            {"forecast_run_id": forecast_run_id},
        )

    # Menu products grouped by category.
    menu_rows = session.execute(
        select(MenuProduct.product_id, Product.category_id)
        .join(Product, Product.id == MenuProduct.product_id)
        .where(MenuProduct.menu_id == menu_id)
    ).all()
    products_by_category: dict[int, list[int]] = {}
    for product_id, category_id in menu_rows:
        products_by_category.setdefault(category_id, []).append(product_id)

    category_names = {
        category.id: category.name
        for category in session.execute(select(Category)).scalars().all()
    }

    # Latest score per menu product.
    latest_period = session.execute(
        select(ProductScore.period_end).order_by(ProductScore.period_end.desc()).limit(1)
    ).scalar()
    scores: dict[int, Decimal] = {}
    if latest_period is not None:
        for product_id, final_score in session.execute(
            select(ProductScore.product_id, ProductScore.final_score).where(
                ProductScore.period_end == latest_period
            )
        ).all():
            scores[product_id] = final_score

    fridge_ids = sorted({result.fridge_id for result in results})
    caps = {
        (cap.fridge_id, cap.product_id): cap.max_qty
        for cap in session.execute(
            select(MenuProductCap).where(MenuProductCap.fridge_id.in_(fridge_ids))
        )
        .scalars()
        .all()
    }
    targets = {
        (target.fridge_id, target.product_id): target.target_qty
        for target in session.execute(
            select(ProductTarget).where(ProductTarget.fridge_id.in_(fridge_ids))
        )
        .scalars()
        .all()
    }
    readings = _fridge_stock_readings(fridge_ids, session)
    # Staleness is decided ONCE PER FRIDGE and reused across that fridge's lines.
    stale_by_fridge = readings.stale_fridge_ids(
        fridge_ids, datetime.datetime.now(datetime.timezone.utc)
    )
    stale_fridge_ids = [fid for fid, stale in stale_by_fridge.items() if stale]
    if stale_fridge_ids:
        logger.warning(
            "menu allocation %s: fridge_stock reading stale or absent for fridges "
            "%s (max age=%s) - their target replenishment uses last-known units "
            "and is flagged stock_stale",
            menu_id, stale_fridge_ids, STOCK_READING_MAX_AGE,
        )

    lines: list[AllocationLine] = []
    for result in results:
        product_ids = products_by_category.get(result.category_id, [])
        if not product_ids:
            continue

        name = category_names.get(result.category_id, "").lower()
        is_target_category = any(token in name for token in _TARGET_CATEGORY_TOKENS)

        if is_target_category:
            for product_id in product_ids:
                target_qty = targets.get((result.fridge_id, product_id))
                if target_qty is None:
                    continue
                live = readings.units(result.fridge_id, product_id)
                restock = max(target_qty - live, 0)
                if restock > 0:
                    lines.append(
                        AllocationLine(
                            fridge_id=result.fridge_id,
                            category_id=result.category_id,
                            product_id=product_id,
                            qty=restock,
                            source=SOURCE_TARGET,
                            stock_stale=stale_by_fridge[result.fridge_id],
                        )
                    )
            continue

        target_total = int(result.forecast_qty.to_integral_value(rounding="ROUND_HALF_UP"))
        if target_total <= 0:
            continue

        weights = [scores.get(pid, Decimal("0")) for pid in product_ids]
        if sum(weights, Decimal("0")) <= 0:
            weights = [Decimal("1")] * len(product_ids)

        allocations = _largest_remainder(target_total, weights)
        fridge_caps = {
            pid: caps[(result.fridge_id, pid)]
            for pid in product_ids
            if (result.fridge_id, pid) in caps
        }
        allocations = _apply_caps(product_ids, allocations, fridge_caps, weights)

        for product_id, qty in zip(product_ids, allocations):
            if qty > 0:
                lines.append(
                    AllocationLine(
                        fridge_id=result.fridge_id,
                        category_id=result.category_id,
                        product_id=product_id,
                        qty=qty,
                        source=SOURCE_FORECAST,
                    )
                )

    return lines
