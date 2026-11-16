"""Which calendar days a fridge sells on: shared by the forecast and the fridge-stock rules."""

from __future__ import annotations

import datetime

WEEKEND_ISO_WEEKDAYS = (6, 7)  # Saturday, Sunday
NO_BANK_HOLIDAYS: frozenset[datetime.date] = frozenset()


def is_selling_day(
    day: datetime.date,
    active_on_weekends: bool,
    bank_holidays: frozenset[datetime.date] = NO_BANK_HOLIDAYS,
) -> bool:
    """No fridge sells on a bank holiday; one closed on weekends sells nothing on Sat/Sun."""
    if day in bank_holidays:
        return False
    return active_on_weekends or day.isoweekday() not in WEEKEND_ISO_WEEKDAYS


def count_selling_days(
    first_day: datetime.date,
    length_days: int,
    active_on_weekends: bool,
    bank_holidays: frozenset[datetime.date] = NO_BANK_HOLIDAYS,
) -> int:
    """Selling days among the ``length_days`` calendar days starting at ``first_day``."""
    calendar_days = [first_day + datetime.timedelta(days=offset) for offset in range(length_days)]
    selling_days = [
        day for day in calendar_days if is_selling_day(day, active_on_weekends, bank_holidays)
    ]
    return len(selling_days)
