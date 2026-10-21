"""Forecast method contract: a method decides which days of sales the formula averages."""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass

THREE_WEEKS_DAYS = 21
THIRTEEN_WEEKS_DAYS = 91
# 52 whole weeks, so last year's window starts on the same weekday as this year's.
ONE_YEAR_BACK_DAYS = 364


@dataclass(frozen=True)
class SalesWindow:
    """Local calendar days from ``start`` (inclusive) to ``end`` (exclusive)."""

    start: datetime.date
    end: datetime.date

    @property
    def days(self) -> int:
        return (self.end - self.start).days


class ForecastStrategy(ABC):
    code: str
    label: str

    @abstractmethod
    def sales_window(self, delivery_date: datetime.date) -> SalesWindow:
        """The sales days this method averages for a delivery on ``delivery_date``."""


def window_ending_before(end: datetime.date, length_days: int) -> SalesWindow:
    """The ``length_days`` days that end the day before ``end``."""
    return SalesWindow(start=end - datetime.timedelta(days=length_days), end=end)


def same_weekday_last_year(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=ONE_YEAR_BACK_DAYS)
