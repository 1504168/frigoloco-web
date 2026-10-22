"""Moving average over the 3 weeks (21 days) before the delivery date."""

from __future__ import annotations

import datetime

from app.services.forecast.strategies.base import (
    THREE_WEEKS_DAYS,
    ForecastStrategy,
    SalesWindow,
    window_ending_before,
)


class MovingAverage3Weeks(ForecastStrategy):
    code = "moving_average_3w"
    label = "Last 3 weeks"

    def sales_window(self, delivery_date: datetime.date) -> SalesWindow:
        return window_ending_before(delivery_date, THREE_WEEKS_DAYS)
