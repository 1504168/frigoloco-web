"""Coverage end: how long fridge stock must stay sellable to count as good."""

import datetime

from app.services.fridge_stock_service import coverage_end

FRIDAY = datetime.date(2026, 11, 13)
MONDAY = datetime.date(2026, 11, 16)
SATURDAY = datetime.date(2026, 11, 14)
WEDNESDAY = datetime.date(2026, 11, 18)
EASTER_MONDAY_2027 = datetime.date(2027, 3, 29)
FRIDAY_BEFORE_EASTER_2027 = datetime.date(2027, 3, 26)


def test_site_closed_on_weekends_only_needs_stock_until_saturday():
    assert coverage_end(FRIDAY, 3, active_on_weekends=False) == SATURDAY


def test_site_open_on_weekends_needs_stock_until_next_delivery():
    assert coverage_end(FRIDAY, 3, active_on_weekends=True) == MONDAY


def test_weekday_window_without_closed_days_ends_at_next_delivery():
    assert coverage_end(MONDAY, 2, active_on_weekends=False) == WEDNESDAY


def test_bank_holiday_inside_the_window_is_a_closed_day():
    thursday = datetime.date(2027, 3, 25)
    bank_holidays = frozenset({EASTER_MONDAY_2027})
    end = coverage_end(thursday, 5, active_on_weekends=True, bank_holidays=bank_holidays)
    assert end == EASTER_MONDAY_2027


def test_closed_next_delivery_day_does_not_shorten_the_window():
    bank_holidays = frozenset({EASTER_MONDAY_2027})
    end = coverage_end(
        FRIDAY_BEFORE_EASTER_2027,
        3,
        active_on_weekends=True,
        bank_holidays=bank_holidays,
    )
    assert end == EASTER_MONDAY_2027
