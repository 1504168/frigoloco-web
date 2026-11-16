"""Sales speed per fridge x category for the menu import (spec 0010).

How fast a category really sells since its last delivery, against what that delivery's
original forecast planned, scales the new forecast up or down:

* the previous delivery is the category's last restock ADDED event in the fridge;
* an hourly sales profile (how busy each weekday is x how busy each hour is, from the
  last :data:`PROFILE_LOOKBACK` of sales) spreads that delivery's forecast over time;
* ``remaining`` = the forecast's profile share from now until the next delivery;
* ``pace`` = (units sold since the delivery + ``remaining``) / the forecast for the
  time until the next delivery;
* the new quantity is the forecast x pace, kept between :data:`SALES_SPEED_FLOOR`
  and :data:`SALES_SPEED_CEILING`. With fewer than :data:`MIN_EXPECTED_UNITS_FOR_PACE`
  units planned by now the pace is noise: no change.

A raise is held back for a product whose shelf life ends before the delivery's coverage
end (:func:`fridge_stock_service.coverage_end`): its extra units would expire unsold.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.master import Fridge, FridgeDeliveryConfig, Product
from app.models.planning import ForecastResult, ForecastRun
from app.services import fridge_stock_service, replenishment_service
from app.services.replenishment_service import LOCAL_TIMEZONE, delivery_start
from app.services.selling_days import is_selling_day

MIN_EXPECTED_UNITS_FOR_PACE = Decimal("5")
SALES_SPEED_FLOOR = Decimal("0.50")
SALES_SPEED_CEILING = Decimal("2.00")
NO_CHANGE_FACTOR = Decimal("1")
PROFILE_LOOKBACK = datetime.timedelta(weeks=8)
# About one sale per day over the lookback: below it the shape is noise.
MIN_PROFILE_UNITS = 56
LINEAR_HOUR_WEIGHT = Decimal(1)
ZERO_WEIGHT = Decimal(0)
SECONDS_PER_HOUR = Decimal(3600)
ONE_HOUR = datetime.timedelta(hours=1)
TWO_PLACES = Decimal("0.01")

HOURLY_SALES_SQL = text(
    """
    SELECT sale.fridge_id,
           product.category_id,
           CAST(extract(isodow FROM sale.sold_at AT TIME ZONE :timezone) AS int) AS iso_weekday,
           CAST(extract(hour FROM sale.sold_at AT TIME ZONE :timezone) AS int) AS local_hour,
           count(*) AS sold_units
    FROM sales_events AS sale
    JOIN products AS product ON product.id = sale.product_id
    WHERE NOT sale.is_refunded
      AND product.category_id = ANY(:category_ids)
      AND sale.sold_at >= :profile_start
      AND sale.sold_at < :profile_end
    GROUP BY sale.fridge_id, product.category_id, iso_weekday, local_hour
    """
)


class ProfileSource(StrEnum):
    """Whose sales shaped the hourly profile."""

    FRIDGE = "fridge"
    CATEGORY = "category"
    LINEAR = "linear"


@dataclass
class SalesCounts:
    """Units sold per ISO weekday and per local hour (the two halves of a profile)."""

    units_by_weekday: dict[int, int] = field(default_factory=dict)
    units_by_hour: dict[int, int] = field(default_factory=dict)
    total_units: int = 0

    def add(self, iso_weekday: int, local_hour: int, sold_units: int) -> None:
        self.units_by_weekday[iso_weekday] = self.units_by_weekday.get(iso_weekday, 0) + sold_units
        self.units_by_hour[local_hour] = self.units_by_hour.get(local_hour, 0) + sold_units
        self.total_units += sold_units


NO_SALES_COUNTS = SalesCounts()


@dataclass(frozen=True)
class HourlySalesProfile:
    """Relative sales weight of every hour; a closed day weighs nothing.

    The weight of an hour is (units sold on its weekday) x (units sold in its hour of
    day). Another factor (weather) would multiply into :meth:`hour_weight`.
    """

    source: ProfileSource
    counts: SalesCounts
    active_on_weekends: bool

    def hour_weight(self, hour_start: datetime.datetime) -> Decimal:
        local_start = hour_start.astimezone(LOCAL_TIMEZONE)
        if not is_selling_day(local_start.date(), self.active_on_weekends):
            return ZERO_WEIGHT
        if self.source is ProfileSource.LINEAR:
            return LINEAR_HOUR_WEIGHT
        weekday_units = self.counts.units_by_weekday.get(local_start.isoweekday(), 0)
        hour_units = self.counts.units_by_hour.get(local_start.hour, 0)
        return Decimal(weekday_units * hour_units)

    def sales_weight(self, start: datetime.datetime, end: datetime.datetime) -> Decimal:
        """Summed hour weights between ``start`` and ``end``, partial hours prorated."""
        total_weight = ZERO_WEIGHT
        # Brussels offsets are whole hours, so a UTC hour is also a local hour.
        hour_start = start.astimezone(datetime.UTC).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        while hour_start < end:
            hour_end = hour_start + ONE_HOUR
            covered = min(end, hour_end) - max(start, hour_start)
            covered_share = Decimal(covered.total_seconds()) / SECONDS_PER_HOUR
            total_weight += self.hour_weight(hour_start) * covered_share
            hour_start = hour_end
        return total_weight


@dataclass(frozen=True)
class SalesProfiles:
    """Sales counts per (fridge, category) and per category over all fridges."""

    counts_by_fridge_category: dict[tuple[int, int], SalesCounts]
    counts_by_category: dict[int, SalesCounts]

    def profile_for(
        self,
        *,
        fridge_id: int,
        category_id: int,
        active_on_weekends: bool,
    ) -> HourlySalesProfile:
        """The fridge's own profile, else the category's over all fridges, else linear."""
        fridge_counts = self.counts_by_fridge_category.get(
            (fridge_id, category_id),
            NO_SALES_COUNTS,
        )
        category_counts = self.counts_by_category.get(category_id, NO_SALES_COUNTS)
        if fridge_counts.total_units >= MIN_PROFILE_UNITS:
            source, counts = ProfileSource.FRIDGE, fridge_counts
        elif category_counts.total_units >= MIN_PROFILE_UNITS:
            source, counts = ProfileSource.CATEGORY, category_counts
        else:
            source, counts = ProfileSource.LINEAR, NO_SALES_COUNTS
        return HourlySalesProfile(
            source=source,
            counts=counts,
            active_on_weekends=active_on_weekends,
        )


@dataclass(frozen=True)
class SalesSpeedAdjustment:
    """Why a fridge x category forecast was raised or lowered by its sales speed."""

    fridge_id: int
    category_id: int
    # The previous delivery's original forecast, spread over the time until the next one.
    forecast_units: Decimal
    sold_units: int
    # Forecast units the profile still expects from now until the next delivery.
    remaining_units: Decimal
    pace: Decimal
    factor: Decimal
    profile_source: ProfileSource


@dataclass(frozen=True)
class FillWindow:
    """How long a delivery must last, and whether the fridge sells on weekends."""

    days_to_fill: int
    active_on_weekends: bool


@dataclass(frozen=True)
class ShelfLifeCheck:
    """Shelf life per product and the coverage window per fridge of the new delivery."""

    shelf_life_days_by_product: dict[int, int | None]
    coverage_days_by_fridge: dict[int, int]

    def can_take_raise(self, fridge_id: int, product_id: int) -> bool:
        """An unknown shelf life or coverage window does not block a raise."""
        coverage_days = self.coverage_days_by_fridge.get(fridge_id)
        shelf_life_days = self.shelf_life_days_by_product.get(product_id)
        if coverage_days is None or shelf_life_days is None:
            return True
        return shelf_life_days >= coverage_days


@dataclass(frozen=True)
class ShelfLifeHold:
    """A product kept at its unraised share: its shelf life ends before the coverage end."""

    fridge_id: int
    product_id: int
    raised_qty: int
    kept_qty: int
    shelf_life_days: int
    coverage_days: int


@dataclass(frozen=True)
class ShelfLifeLimitedShares:
    shares: list[int]
    holds: list[ShelfLifeHold]


def load_sales_speed_adjustments(
    *,
    fridge_ids: list[int],
    category_ids: list[int],
    delivery_date: datetime.date,
    session: Session,
) -> dict[tuple[int, int], SalesSpeedAdjustment]:
    """The (fridge, category) pairs whose sales speed changes their forecast."""
    category_sales = replenishment_service.load_category_sales_since_last_delivery(
        fridge_ids=fridge_ids,
        category_ids=category_ids,
        delivery_date=delivery_date,
        session=session,
    )
    previous_delivery_dates = {_local_date(sales.delivered_at) for sales in category_sales}
    previous_forecasts = _load_original_forecast_quantities(
        delivery_dates=previous_delivery_dates,
        fridge_ids=fridge_ids,
        session=session,
    )
    fill_windows = _load_fill_windows(fridge_ids, session)
    next_delivery_start = delivery_start(delivery_date)
    measured_until = min(_now(), next_delivery_start)
    profiles = load_sales_profiles(
        category_ids=category_ids,
        profile_end=delivery_start(measured_until.astimezone(LOCAL_TIMEZONE).date()),
        session=session,
    )

    adjustments: dict[tuple[int, int], SalesSpeedAdjustment] = {}
    for sales in category_sales:
        adjustment = _category_sales_speed(
            sales=sales,
            previous_forecasts=previous_forecasts,
            fill_windows=fill_windows,
            profiles=profiles,
            measured_until=measured_until,
            next_delivery_start=next_delivery_start,
        )
        if adjustment is not None and adjustment.factor != NO_CHANGE_FACTOR:
            adjustments[(sales.fridge_id, sales.category_id)] = adjustment
    return adjustments


def load_sales_profiles(
    *,
    category_ids: list[int],
    profile_end: datetime.datetime,
    session: Session,
) -> SalesProfiles:
    """Non-refunded sales of the lookback, bucketed by Brussels weekday and hour."""
    rows = session.execute(
        HOURLY_SALES_SQL,
        {
            "timezone": str(LOCAL_TIMEZONE),
            "category_ids": category_ids,
            "profile_start": profile_end - PROFILE_LOOKBACK,
            "profile_end": profile_end,
        },
    ).all()
    counts_by_fridge_category: dict[tuple[int, int], SalesCounts] = {}
    counts_by_category: dict[int, SalesCounts] = {}
    for row in rows:
        fridge_counts = counts_by_fridge_category.setdefault(
            (row.fridge_id, row.category_id),
            SalesCounts(),
        )
        fridge_counts.add(row.iso_weekday, row.local_hour, int(row.sold_units))
        category_counts = counts_by_category.setdefault(row.category_id, SalesCounts())
        category_counts.add(row.iso_weekday, row.local_hour, int(row.sold_units))
    return SalesProfiles(
        counts_by_fridge_category=counts_by_fridge_category,
        counts_by_category=counts_by_category,
    )


def sales_speed_factor(pace: Decimal) -> Decimal:
    """The quantity follows the pace, never under the floor nor over the ceiling."""
    return min(max(pace, SALES_SPEED_FLOOR), SALES_SPEED_CEILING)


def apply_sales_speed_factor(category_qty: int, factor: Decimal) -> int:
    """The adjusted quantity, rounded half up to whole units."""
    adjusted_qty = Decimal(category_qty) * factor
    return int(adjusted_qty.to_integral_value(rounding=ROUND_HALF_UP))


def load_shelf_life_check(
    *,
    fridge_ids: list[int],
    product_ids: list[int],
    delivery_date: datetime.date,
    session: Session,
) -> ShelfLifeCheck:
    shelf_life_rows = session.execute(
        select(Product.id, Product.shelf_life_days).where(Product.id.in_(product_ids))
    ).all()
    coverage_end_by_fridge = fridge_stock_service.load_coverage_ends(
        delivery_date=delivery_date,
        fridge_ids=fridge_ids,
        session=session,
    )
    coverage_days_by_fridge = {
        fridge_id: (coverage_end - delivery_date).days
        for fridge_id, coverage_end in coverage_end_by_fridge.items()
    }
    return ShelfLifeCheck(
        shelf_life_days_by_product=dict(shelf_life_rows),
        coverage_days_by_fridge=coverage_days_by_fridge,
    )


def keep_raise_within_shelf_life(
    *,
    fridge_id: int,
    product_ids: list[int],
    raised_shares: list[int],
    unraised_shares: list[int],
    shelf_life_check: ShelfLifeCheck,
) -> ShelfLifeLimitedShares:
    """A product that cannot last the coverage window keeps its unraised share.

    The units it gives up are not moved to other products: the raise is a guess about
    demand, and pushing it onto fewer products would overstock them.
    """
    shares: list[int] = []
    holds: list[ShelfLifeHold] = []
    for product_id, raised_qty, unraised_qty in zip(product_ids, raised_shares, unraised_shares):
        is_held = raised_qty > unraised_qty and not shelf_life_check.can_take_raise(
            fridge_id,
            product_id,
        )
        if not is_held:
            shares.append(raised_qty)
            continue
        shares.append(unraised_qty)
        holds.append(
            ShelfLifeHold(
                fridge_id=fridge_id,
                product_id=product_id,
                raised_qty=raised_qty,
                kept_qty=unraised_qty,
                shelf_life_days=shelf_life_check.shelf_life_days_by_product[product_id],
                coverage_days=shelf_life_check.coverage_days_by_fridge[fridge_id],
            )
        )
    return ShelfLifeLimitedShares(shares=shares, holds=holds)


def _category_sales_speed(
    *,
    sales: replenishment_service.CategorySalesSinceDelivery,
    previous_forecasts: dict[tuple[datetime.date, int, int], Decimal],
    fill_windows: dict[tuple[int, int], FillWindow],
    profiles: SalesProfiles,
    measured_until: datetime.datetime,
    next_delivery_start: datetime.datetime,
) -> SalesSpeedAdjustment | None:
    """None without a previous forecast or window, or with too few units planned by now."""
    previous_delivery_date = _local_date(sales.delivered_at)
    forecast_key = (previous_delivery_date, sales.fridge_id, sales.category_id)
    original_forecast = previous_forecasts.get(forecast_key)
    fill_window = fill_windows.get((sales.fridge_id, previous_delivery_date.isoweekday()))
    if original_forecast is None or fill_window is None:
        return None
    profile = profiles.profile_for(
        fridge_id=sales.fridge_id,
        category_id=sales.category_id,
        active_on_weekends=fill_window.active_on_weekends,
    )
    window_end = delivery_start(
        previous_delivery_date + datetime.timedelta(days=fill_window.days_to_fill)
    )
    window_weight = profile.sales_weight(sales.delivered_at, window_end)
    if window_weight == ZERO_WEIGHT:
        return None
    elapsed_weight = profile.sales_weight(sales.delivered_at, measured_until)
    remaining_weight = profile.sales_weight(measured_until, next_delivery_start)
    units_per_weight = original_forecast / window_weight
    expected_by_now = units_per_weight * elapsed_weight
    if expected_by_now < MIN_EXPECTED_UNITS_FOR_PACE:
        return None
    forecast_units = units_per_weight * (elapsed_weight + remaining_weight)
    remaining_units = units_per_weight * remaining_weight
    pace = (Decimal(sales.sold_qty) + remaining_units) / forecast_units
    return SalesSpeedAdjustment(
        fridge_id=sales.fridge_id,
        category_id=sales.category_id,
        forecast_units=forecast_units.quantize(TWO_PLACES),
        sold_units=sales.sold_qty,
        remaining_units=remaining_units.quantize(TWO_PLACES),
        pace=pace.quantize(TWO_PLACES),
        factor=sales_speed_factor(pace).quantize(TWO_PLACES),
        profile_source=profile.source,
    )


def _load_original_forecast_quantities(
    *,
    delivery_dates: set[datetime.date],
    fridge_ids: list[int],
    session: Session,
) -> dict[tuple[datetime.date, int, int], Decimal]:
    """Saved forecast per (delivery date, fridge, category): gross (before stock) if stored."""
    rows = session.execute(
        select(
            ForecastRun.delivery_date,
            ForecastResult.fridge_id,
            ForecastResult.category_id,
            ForecastResult.forecast_qty,
            ForecastResult.gross_qty,
        )
        .join(ForecastRun, ForecastRun.id == ForecastResult.run_id)
        .where(
            ForecastRun.is_saved.is_(True),
            ForecastRun.delivery_date.in_(delivery_dates),
            ForecastResult.fridge_id.in_(fridge_ids),
        )
    ).all()
    original_forecasts: dict[tuple[datetime.date, int, int], Decimal] = {}
    for row in rows:
        forecast_key = (row.delivery_date, row.fridge_id, row.category_id)
        if row.gross_qty is None:
            original_forecasts[forecast_key] = row.forecast_qty
        else:
            original_forecasts[forecast_key] = row.gross_qty
    return original_forecasts


def _load_fill_windows(
    fridge_ids: list[int],
    session: Session,
) -> dict[tuple[int, int], FillWindow]:
    """Fill window per (fridge, ISO weekday of the delivery)."""
    rows = session.execute(
        select(
            FridgeDeliveryConfig.fridge_id,
            FridgeDeliveryConfig.weekday,
            FridgeDeliveryConfig.days_to_fill,
            Fridge.active_on_weekends,
        )
        .join(Fridge, Fridge.id == FridgeDeliveryConfig.fridge_id)
        .where(FridgeDeliveryConfig.fridge_id.in_(fridge_ids))
    ).all()
    return {
        (row.fridge_id, row.weekday): FillWindow(
            days_to_fill=row.days_to_fill,
            active_on_weekends=row.active_on_weekends,
        )
        for row in rows
    }


def _local_date(moment: datetime.datetime) -> datetime.date:
    return moment.astimezone(LOCAL_TIMEZONE).date()


def _now() -> datetime.datetime:
    return datetime.datetime.now(LOCAL_TIMEZONE)
