"""Next supplier delivery date and order deadline from the supplier's weekly schedule."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.master import SupplierDeliverySchedule

LOCAL_TIMEZONE = ZoneInfo("Europe/Brussels")
DAYS_PER_WEEK = 7
# A cutoff is at most 6 days before its delivery, so two weeks always holds an open slot.
SEARCH_HORIZON_DAYS = 2 * DAYS_PER_WEEK


@dataclass(frozen=True)
class NextDelivery:
    delivery_date: datetime.date
    order_deadline: datetime.datetime


def find_next_supplier_delivery(
    session: Session,
    supplier_id: int,
    ordered_at: datetime.datetime,
) -> NextDelivery | None:
    """Earliest delivery whose order deadline is not yet passed at ``ordered_at``."""
    schedules = session.execute(
        select(SupplierDeliverySchedule).where(
            SupplierDeliverySchedule.supplier_id == supplier_id
        )
    ).scalars().all()
    return next_delivery_from_schedule(list(schedules), ordered_at)


def next_delivery_from_schedule(
    schedules: list[SupplierDeliverySchedule],
    ordered_at: datetime.datetime,
) -> NextDelivery | None:
    """None when the supplier has no delivery days; naive ``ordered_at`` is Brussels time."""
    local_ordered_at = _as_local_time(ordered_at)
    schedule_by_weekday = {schedule.delivery_weekday: schedule for schedule in schedules}
    if not schedule_by_weekday:
        return None
    for day_offset in range(SEARCH_HORIZON_DAYS):
        delivery_date = local_ordered_at.date() + datetime.timedelta(days=day_offset)
        schedule = schedule_by_weekday.get(delivery_date.isoweekday())
        if schedule is None:
            continue
        order_deadline = _order_deadline(schedule, delivery_date)
        if order_deadline >= local_ordered_at:
            return NextDelivery(delivery_date=delivery_date, order_deadline=order_deadline)
    return None


def days_before_delivery(delivery_weekday: int, cutoff_weekday: int) -> int:
    """Whole days between the cutoff weekday and the delivery weekday (0 = same day)."""
    return (delivery_weekday - cutoff_weekday) % DAYS_PER_WEEK


def _order_deadline(
    schedule: SupplierDeliverySchedule,
    delivery_date: datetime.date,
) -> datetime.datetime:
    lead_days = days_before_delivery(schedule.delivery_weekday, schedule.cutoff_weekday)
    cutoff_date = delivery_date - datetime.timedelta(days=lead_days)
    return datetime.datetime.combine(cutoff_date, schedule.cutoff_time, tzinfo=LOCAL_TIMEZONE)


def _as_local_time(moment: datetime.datetime) -> datetime.datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=LOCAL_TIMEZONE)
    return moment.astimezone(LOCAL_TIMEZONE)
