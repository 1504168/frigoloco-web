"""Moving average over the 13 weeks (91 days, about 3 months) before delivery (or today)."""

from __future__ import annotations

import datetime

from app.services.forecast.strategies.base import (
    THIRTEEN_WEEKS_DAYS,
    ForecastStrategy,
    SalesWindow,
    recent_window,
)


class MovingAverage3Months(ForecastStrategy):
    code = "moving_average_3m"
    label = "Last 3 months"

    def sales_window(
        self,
        delivery_date: datetime.date,
        sales_until: datetime.date,
    ) -> SalesWindow:
        return recent_window(delivery_date, sales_until, THIRTEEN_WEEKS_DAYS)
