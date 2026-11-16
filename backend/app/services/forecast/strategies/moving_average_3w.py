"""Moving average over the 3 weeks (21 days) before the delivery date (or before today)."""

from __future__ import annotations

import datetime

from app.services.forecast.strategies.base import (
    THREE_WEEKS_DAYS,
    ForecastStrategy,
    SalesWindow,
    recent_window,
)


class MovingAverage3Weeks(ForecastStrategy):
    code = "moving_average_3w"
    label = "Last 3 weeks"

    def sales_window(
        self,
        delivery_date: datetime.date,
        sales_until: datetime.date,
    ) -> SalesWindow:
        return recent_window(delivery_date, sales_until, THREE_WEEKS_DAYS)
