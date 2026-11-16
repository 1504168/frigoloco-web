"""Read-only week views over dispatch lines: warm dish distribution and week comparison.

Warm dishes are the categories whose name says so ("2. Warm Dishes", "3. Warm Dishes
Jar", "10. Frozen Warm Dishes"; French "chaud" too). The week comparison sums the
units per category of a week, the week before and the same ISO week a year earlier.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import DispatchStatus
from app.services.stock_service import resolve_delivery_date

WARM_CATEGORY_NAME_PATTERNS = ["%warm%", "%chaud%"]
DISPATCHED_STATUSES = [
    DispatchStatus.dispatched.value,
    DispatchStatus.reconciled.value,
]
PLANNED_OR_DISPATCHED_STATUSES = [
    DispatchStatus.saved.value,
    *DISPATCHED_STATUSES,
]
DAYS_PER_WEEK = 7
MONDAY = 1
WEEK_START_DAY_NAME = "Monday"
# 28 December always falls in the last ISO week of its year.
DECEMBER = 12
LAST_WEEK_DAY = 28

WARM_DISTRIBUTION_SQL = text(
    """
    SELECT
        d.delivery_date AS delivery_date,
        dl.fridge_id AS fridge_id,
        f.friendly_name AS friendly_name,
        dl.product_id AS product_id,
        p.name AS product_name,
        c.name AS category_name,
        SUM(dl.qty) AS qty
    FROM dispatch_lines dl
    JOIN dispatches d ON d.id = dl.dispatch_id
    JOIN fridges f ON f.id = dl.fridge_id
    JOIN products p ON p.id = dl.product_id
    JOIN categories c ON c.id = p.category_id
    WHERE d.week_start = :week_start
      AND dl.delivery_date >= :week_start
      AND dl.delivery_date < :next_week_start
      AND d.status = ANY(:statuses)
      AND c.name ILIKE ANY(:warm_patterns)
    GROUP BY d.delivery_date, dl.fridge_id, f.friendly_name, dl.product_id, p.name, c.name
    ORDER BY p.name, f.friendly_name, d.delivery_date
    """
)

UNITS_PER_WEEK_AND_CATEGORY_SQL = text(
    """
    SELECT
        d.week_start AS week_start,
        c.id AS category_id,
        c.name AS category_name,
        c.display_order AS display_order,
        SUM(dl.qty) AS units
    FROM dispatch_lines dl
    JOIN dispatches d ON d.id = dl.dispatch_id
    JOIN products p ON p.id = dl.product_id
    JOIN categories c ON c.id = p.category_id
    WHERE d.week_start = ANY(:week_starts)
      AND d.status = ANY(:statuses)
    GROUP BY d.week_start, c.id, c.name, c.display_order
    ORDER BY c.display_order, c.name
    """
)


@dataclass(frozen=True)
class WarmDishLine:
    delivery_date: datetime.date
    fridge_id: int
    friendly_name: str
    product_id: int
    product_name: str
    category_name: str
    qty: int


@dataclass(frozen=True)
class ComparedWeek:
    year: int
    week: int
    week_start: datetime.date


@dataclass(frozen=True)
class CategoryWeekUnits:
    category_id: int
    category_name: str
    this_week_units: int
    previous_week_units: int
    last_year_units: int


@dataclass(frozen=True)
class WeekComparison:
    this_week: ComparedWeek
    previous_week: ComparedWeek
    same_week_last_year: ComparedWeek
    categories: list[CategoryWeekUnits]


def list_warm_dish_lines(
    *,
    year: int,
    week: int,
    include_planned: bool,
    session: Session,
) -> list[WarmDishLine]:
    """Warm dish units per delivery day, fridge and product for an ISO week."""
    week_start = resolve_delivery_date(year, week, WEEK_START_DAY_NAME)
    statuses = PLANNED_OR_DISPATCHED_STATUSES if include_planned else DISPATCHED_STATUSES
    rows = session.execute(
        WARM_DISTRIBUTION_SQL,
        {
            "week_start": week_start,
            "next_week_start": week_start + datetime.timedelta(days=DAYS_PER_WEEK),
            "statuses": statuses,
            "warm_patterns": WARM_CATEGORY_NAME_PATTERNS,
        },
    ).all()
    return [
        WarmDishLine(
            delivery_date=row.delivery_date,
            fridge_id=row.fridge_id,
            friendly_name=row.friendly_name,
            product_id=row.product_id,
            product_name=row.product_name,
            category_name=row.category_name,
            qty=int(row.qty),
        )
        for row in rows
    ]


def compare_week(*, year: int, week: int, session: Session) -> WeekComparison:
    """Planned or dispatched units per category: this week, the week before, a year before."""
    this_week = ComparedWeek(
        year=year,
        week=week,
        week_start=resolve_delivery_date(year, week, WEEK_START_DAY_NAME),
    )
    previous_monday = this_week.week_start - datetime.timedelta(days=DAYS_PER_WEEK)
    previous_year, previous_week_no, _ = previous_monday.isocalendar()
    previous_week = ComparedWeek(
        year=previous_year,
        week=previous_week_no,
        week_start=previous_monday,
    )
    same_week_last_year = _same_week_last_year(year, week)

    compared_week_starts = [
        this_week.week_start,
        previous_week.week_start,
        same_week_last_year.week_start,
    ]
    rows = session.execute(
        UNITS_PER_WEEK_AND_CATEGORY_SQL,
        {"week_starts": compared_week_starts, "statuses": PLANNED_OR_DISPATCHED_STATUSES},
    ).all()

    category_names: dict[int, str] = {}
    units_by_week_and_category: dict[tuple[datetime.date, int], int] = {}
    for row in rows:
        category_names[row.category_id] = row.category_name
        units_by_week_and_category[(row.week_start, row.category_id)] = int(row.units)

    def units_of(compared: ComparedWeek, category_id: int) -> int:
        return units_by_week_and_category.get((compared.week_start, category_id), 0)

    categories = [
        CategoryWeekUnits(
            category_id=category_id,
            category_name=category_name,
            this_week_units=units_of(this_week, category_id),
            previous_week_units=units_of(previous_week, category_id),
            last_year_units=units_of(same_week_last_year, category_id),
        )
        for category_id, category_name in category_names.items()
    ]
    return WeekComparison(
        this_week=this_week,
        previous_week=previous_week,
        same_week_last_year=same_week_last_year,
        categories=categories,
    )


def _same_week_last_year(year: int, week: int) -> ComparedWeek:
    """The same ISO week a year earlier; week 53 maps to week 52 when last year had none."""
    last_year = year - 1
    _, weeks_in_last_year, _ = datetime.date(last_year, DECEMBER, LAST_WEEK_DAY).isocalendar()
    compared_week = min(week, weeks_in_last_year)
    week_start = datetime.date.fromisocalendar(last_year, compared_week, MONDAY)
    return ComparedWeek(year=last_year, week=compared_week, week_start=week_start)
