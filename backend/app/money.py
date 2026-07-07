"""Money handling: integer *minor units* (cents) end-to-end, euros only at the edge.

Decision (2026-07-03, user): every monetary column is stored as ``bigint`` minor
units (cents), matching the Husky API's ``int64`` contract. Euros exist only as a
presentation format — the HTTP JSON contract is unchanged (a fixed 2-decimal euro
string such as ``"123.45"``), so the frontend is untouched.

This module is the single home for the three boundary conversions:

* :func:`euros_to_cents` — parse a euro amount (decimal string/number) written by
  a client into integer cents on the way *in*.
* :func:`cents_to_euro_str` — render stored integer cents as a euro string on the
  way *out* (the ``MoneyCell``-compatible ``"123.45"`` format).
* :func:`to_cents` — round a cents-valued ``Decimal`` (produced wherever a
  division/fraction is unavoidable — VAT splits, margins, fee percentages) to a
  whole-cent ``int``, half-up.

The Pydantic annotations :data:`MoneyIn` (request) and :data:`MoneyStr` (response)
wire these into the schema layer so no router or service re-implements them.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

_CENTS = Decimal("100")
_WHOLE = Decimal("1")


def euros_to_cents(value: Decimal | int | float | str) -> int:
    """Parse a euro amount into integer minor units (cents), rounded half-up.

    Accepts anything ``Decimal(str(...))`` can parse — decimal strings such as
    ``"12.34"`` (the client wire format), ints, floats and ``Decimal``.
    """
    return int((Decimal(str(value)) * _CENTS).quantize(_WHOLE, rounding=ROUND_HALF_UP))


def to_cents(value: Decimal | int) -> int:
    """Round a cents-valued ``Decimal`` to whole cents (half-up) and return an int.

    Use at the end of any computation that produced fractional cents (a VAT split,
    a fee percentage, a per-1.06 turnover division).
    """
    return int(Decimal(value).quantize(_WHOLE, rounding=ROUND_HALF_UP))


def cents_to_euro_str(cents: int) -> str:
    """Render integer minor units as a fixed 2-decimal euro string (``"123.45"``).

    Sign-aware so negative diffs/margins serialize as ``"-8.00"``.
    """
    whole = int(cents)
    sign = "-" if whole < 0 else ""
    whole = abs(whole)
    return f"{sign}{whole // 100}.{whole % 100:02d}"


def cents_to_euro_decimal(cents: int) -> Decimal:
    """Integer minor units to a euro ``Decimal`` (for internal reuse of euro DTOs)."""
    return (Decimal(int(cents)) / _CENTS).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Pydantic annotations
# ---------------------------------------------------------------------------

# Request money: a euro decimal string/number on the wire, stored as int cents.
MoneyIn = Annotated[int, BeforeValidator(euros_to_cents)]

# Response money: an int (cents) in Python, a euro string on the JSON boundary.
MoneyStr = Annotated[
    int,
    PlainSerializer(lambda v: cents_to_euro_str(int(v)), return_type=str, when_used="json"),
]
