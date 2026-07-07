"""Pure field-normalisation helpers for Husky payloads (unit-tested, no I/O).

Design notes
------------
* Prices arrive as ``int64`` *minor units* (cents). The DB stores money as
  ``BIGINT`` cents too (migration 0002, 2026-07-03), so ingestion writes the
  vendor cents RAW — no conversion. ``minor_units_to_euros`` and
  ``sum_discount_paid`` remain for *presentation* only (unit-tested);
  ``sum_discount_minor_units`` is the raw-cents ingestion counterpart.
* ``is_refunded`` = any ``refundStatus`` entry whose status string contains
  "refunded" (case-insensitive) — per the implementation brief.
* VAT is delivered "as a percentage" (e.g. ``6.0`` for 6 %); the DB column is a
  fraction in ``[0, 1)`` (``vat_rate``), so ``normalize_vat_fraction`` divides
  by 100 when the value looks like a percentage.

The typed response models live in :mod:`app.husky.schemas`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# ---------------------------------------------------------------------------
# Pure normalisation helpers (unit-tested, no I/O)
# ---------------------------------------------------------------------------

_REFUNDED_TOKEN = "refunded"


def minor_units_to_euros(value: int | str | None) -> Decimal | None:
    """Convert Husky ``int64`` minor units (cents) to a euro ``Decimal``.

    ``None`` passes through as ``None``. Strings are accepted (some CSV/Excel
    paths deliver stringified integers). ``Decimal(str(value)) / 100`` keeps the
    conversion exact and free of binary-float drift.
    """
    if value is None:
        return None
    try:
        cents = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"cannot parse minor units: {value!r}") from exc
    return cents / Decimal(100)


def parse_decimal(value: Any) -> Decimal | None:
    """Parse a possibly comma-decimal string/number into a ``Decimal``.

    Handles European ``"1,50"`` and thousands separators (``"1.234,50"``),
    plain ``"1.50"``, and native ``int``/``float``/``Decimal``. Empty/``None``
    yields ``None``.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    if "," in text and "." in text:
        # Assume '.' is the thousands separator and ',' the decimal separator.
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"cannot parse decimal: {value!r}") from exc


def euros_to_minor_units(value: Any) -> int | None:
    """Convert a euro amount (number or decimal string) to ``int`` minor units.

    The Husky ``producttype.reference`` field carries the BUY price as a euro
    *decimal string* (e.g. ``"5.95"``), unlike ``price`` which is already integer
    cents. The DB stores money as ``BIGINT`` cents, so a euro value must be scaled
    by 100 and rounded to the nearest cent (``ROUND_HALF_UP``). ``None``/empty
    yields ``None``.
    """
    euros = parse_decimal(value)
    if euros is None:
        return None
    return int((euros * Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def is_refunded(refund_statuses: list[dict[str, Any]] | None) -> bool:
    """True if any refund-status entry's ``status`` contains "refunded"."""
    if not refund_statuses:
        return False
    for entry in refund_statuses:
        status = str(entry.get("status", "")) if isinstance(entry, dict) else ""
        if _REFUNDED_TOKEN in status.casefold():
            return True
    return False


def normalize_vat_fraction(value: Any) -> Decimal | None:
    """Normalise a VAT value to a fraction in ``[0, 1)``.

    Husky returns VAT "as a percentage" (``6.0`` -> ``0.06``). Values already
    expressed as a fraction (``< 1``) are passed through unchanged.
    """
    parsed = parse_decimal(value)
    if parsed is None:
        return None
    if parsed >= Decimal(1):
        return parsed / Decimal(100)
    return parsed


def sum_discount_paid(discounts: list[dict[str, Any]] | None) -> Decimal:
    """Sum the ``paidAmount`` minor units across a product's discounts (euros).

    Presentation helper — for ingestion use :func:`sum_discount_minor_units`.
    """
    total = Decimal(0)
    if not discounts:
        return total
    for entry in discounts:
        if not isinstance(entry, dict):
            continue
        paid = entry.get("paidAmount")
        euros = minor_units_to_euros(paid)
        if euros is not None:
            total += euros
    return total


def sum_discount_minor_units(discounts: list[dict[str, Any]] | None) -> int:
    """Sum the RAW ``paidAmount`` minor units (cents) across a product's discounts.

    Ingestion counterpart of :func:`sum_discount_paid`: keeps the vendor cents raw
    for the ``BIGINT`` ``discount_amount`` column (no euro conversion)."""
    total = 0
    if not discounts:
        return total
    for entry in discounts:
        if not isinstance(entry, dict):
            continue
        paid = entry.get("paidAmount")
        if paid is None:
            continue
        try:
            total += int(str(paid).strip())
        except (TypeError, ValueError):
            continue
    return total


def first_discount_provider(discounts: list[dict[str, Any]] | None) -> str | None:
    """Return the first discount provider name, if any."""
    if not discounts:
        return None
    for entry in discounts:
        if isinstance(entry, dict) and entry.get("provider"):
            return str(entry["provider"])
    return None
