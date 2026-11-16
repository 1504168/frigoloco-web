"""Last year's 3 months: the 91-day window before delivery, shifted back 52 weeks."""

from __future__ import annotations

import datetime

from app.services.forecast.strategies.base import (
    THIRTEEN_WEEKS_DAYS,
    ForecastStrategy,
    SalesWindow,
    same_weekday_last_year,
    window_ending_before,
)


class LastYear3Months(ForecastStrategy):
    code = "last_year_3m"
    label = "Last year, same 3 months"

    def sales_window(
        self,
        delivery_date: datetime.date,
        sales_until: datetime.date,
    ) -> SalesWindow:
        # A year back is always complete history, so ``sales_until`` never cuts it.
        return window_ending_before(same_weekday_last_year(delivery_date), THIRTEEN_WEEKS_DAYS)
