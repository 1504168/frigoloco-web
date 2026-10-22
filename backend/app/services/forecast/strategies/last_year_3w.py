"""Last year's 3 weeks: the 21-day window before delivery, shifted back 52 weeks."""

from __future__ import annotations

import datetime

from app.services.forecast.strategies.base import (
    THREE_WEEKS_DAYS,
    ForecastStrategy,
    SalesWindow,
    same_weekday_last_year,
    window_ending_before,
)


class LastYear3Weeks(ForecastStrategy):
    code = "last_year_3w"
    label = "Last year, same 3 weeks"

    def sales_window(self, delivery_date: datetime.date) -> SalesWindow:
        return window_ending_before(same_weekday_last_year(delivery_date), THREE_WEEKS_DAYS)
