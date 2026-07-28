"""Delivery-config rotation rule.

``days_to_fill`` is never entered by hand: it is derived from the set of
weekdays a fridge is restocked on. For each delivery weekday, it is the number
of days that delivery must cover - the gap (counting the delivery day itself,
but not the next one) until the next delivery in the weekly rotation.

Example: a fridge delivered Thursday (ISO 4) and Sunday (ISO 7) gets
``{4: 3, 7: 4}`` - Thursday covers Thu/Fri/Sat, Sunday covers Sun/Mon/Tue/Wed.
A fridge delivered on a single weekday gets ``7`` (one delivery lasts the week).
"""

from __future__ import annotations

from collections.abc import Iterable

DAYS_PER_WEEK = 7


def compute_days_to_fill(weekdays: Iterable[int]) -> dict[int, int]:
    """Map each delivery weekday (ISO 1-7) to its days-to-fill from the rotation.

    Duplicate weekdays are collapsed. An empty input yields an empty mapping.
    """
    sorted_weekdays = sorted(set(weekdays))
    if not sorted_weekdays:
        return {}

    result: dict[int, int] = {}
    count = len(sorted_weekdays)
    for position, weekday in enumerate(sorted_weekdays):
        next_weekday = sorted_weekdays[(position + 1) % count]
        gap = (next_weekday - weekday) % DAYS_PER_WEEK
        # A single-delivery week (or any exact multiple) wraps to 0 -> full week.
        result[weekday] = gap or DAYS_PER_WEEK
    return result
