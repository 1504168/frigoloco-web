"""Moving average over the 13 weeks (91 days, about 3 months) before the delivery date."""

from __future__ import annotations

import datetime

from app.services.forecast.strategies.base import (
    THIRTEEN_WEEKS_DAYS,
    ForecastStrategy,
    SalesWindow,
    window_ending_before,
)


class MovingAverage3Months(ForecastStrategy):
    code = "moving_average_3m"
    label = "Moving average: last 3 months"

    def sales_window(self, delivery_date: datetime.date) -> SalesWindow:
        return window_ending_before(delivery_date, THIRTEEN_WEEKS_DAYS)
