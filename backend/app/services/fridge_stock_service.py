"""In-fridge stock still good through a delivery's coverage window (deck slide 5).

A unit must stay sellable until the coverage end: the fridge's NEXT delivery
(``delivery_date + days_to_fill``), or sooner, the first day before it on which the site
is closed (a weekend for a fridge closed on weekends, or a bank holiday). Nobody buys on a
closed day, so a unit expiring then is pulled and replaced at the next delivery instead of
now. A unit is good when its RFID tag expiry is on or after the coverage end. A unit whose tag carries no expiry date also counts as good (user
decision 2026-10-28): ``fridge_stock.units`` is the authoritative count and
``expiry_dates`` only lists the tags that have a date. Units expiring sooner are the
withdrawal list (dispatch_service), the exact complement.

Read by the forecast residual deduction (per category) and the menu import's
stock-aware split (per product), so both apply the same rule.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.master import Fridge, FridgeDeliveryConfig
from app.services.forecast.bank_holidays import load_bank_holiday_labels
from app.services.selling_days import NO_BANK_HOLIDAYS, is_selling_day

GOOD_STOCK_UNITS_SQL = text(
    """
    SELECT stock.fridge_id,
           stock.product_id,
           product.category_id,
           stock.taken_at,
           GREATEST(
               stock.units - (
                   SELECT count(*)
                   FROM unnest(stock.expiry_dates) AS tag(expiry)
                   WHERE tag.expiry < coverage.coverage_end
               ),
               0
           ) AS good_units
    FROM unnest(CAST(:fridge_ids AS int[]), CAST(:coverage_ends AS date[]))
         AS coverage(fridge_id, coverage_end)
    JOIN fridge_stock AS stock ON stock.fridge_id = coverage.fridge_id
    JOIN products AS product ON product.id = stock.product_id
    """
)


@dataclass(frozen=True)
class GoodStockUnits:
    """Good units of one product in one fridge, from the reading taken at ``taken_at``."""

    fridge_id: int
    product_id: int
    category_id: int
    good_units: int
    taken_at: datetime.datetime


def coverage_end(
    delivery_date: datetime.date,
    days_to_fill: int,
    active_on_weekends: bool,
    bank_holidays: frozenset[datetime.date] = NO_BANK_HOLIDAYS,
) -> datetime.date:
    """First closed day after the delivery, or the next delivery when the site never closes."""
    next_delivery = delivery_date + datetime.timedelta(days=days_to_fill)
    days_until_next_delivery = [
        delivery_date + datetime.timedelta(days=offset) for offset in range(1, days_to_fill)
    ]
    for day in days_until_next_delivery:
        if not is_selling_day(day, active_on_weekends, bank_holidays):
            return day
    return next_delivery


def load_coverage_ends(
    *,
    delivery_date: datetime.date,
    fridge_ids: list[int],
    session: Session,
) -> dict[int, datetime.date]:
    """Coverage end per fridge with a delivery configured on the delivery's weekday."""
    configs = session.execute(
        select(
            FridgeDeliveryConfig.fridge_id,
            FridgeDeliveryConfig.days_to_fill,
            Fridge.active_on_weekends,
        )
        .join(Fridge, Fridge.id == FridgeDeliveryConfig.fridge_id)
        .where(
            FridgeDeliveryConfig.weekday == delivery_date.isoweekday(),
            FridgeDeliveryConfig.fridge_id.in_(fridge_ids),
        )
    ).all()
    if not configs:
        return {}
    longest_days_to_fill = max(config.days_to_fill for config in configs)
    bank_holidays = frozenset(
        load_bank_holiday_labels(
            delivery_date,
            delivery_date + datetime.timedelta(days=longest_days_to_fill),
            session,
        )
    )
    return {
        config.fridge_id: coverage_end(
            delivery_date,
            config.days_to_fill,
            config.active_on_weekends,
            bank_holidays,
        )
        for config in configs
    }


def load_good_stock_units(
    *,
    coverage_end_by_fridge: dict[int, datetime.date],
    session: Session,
) -> list[GoodStockUnits]:
    """Good units per (fridge, product) from the latest ``fridge_stock`` reading."""
    fridge_ids = list(coverage_end_by_fridge)
    coverage_ends = [coverage_end_by_fridge[fridge_id] for fridge_id in fridge_ids]
    rows = session.execute(
        GOOD_STOCK_UNITS_SQL,
        {"fridge_ids": fridge_ids, "coverage_ends": coverage_ends},
    ).all()
    return [
        GoodStockUnits(
            fridge_id=row.fridge_id,
            product_id=row.product_id,
            category_id=row.category_id,
            good_units=int(row.good_units),
            taken_at=row.taken_at,
        )
        for row in rows
    ]
