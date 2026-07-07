"""Husky (Intelligent Fridges) integration package.

The *only* layer that talks to the vendor API. Split into:

* ``client``    — typed httpx client (Basic auth, throttle, tenacity retry).
* ``schemas``   — pydantic response models (``extra='allow'``).
* ``normalize`` — pure field-normalisation helpers (cents -> euros, refund
                  flag, VAT fraction, …).
* ``archive``   — gzip raw payloads to the raw-first ELT archive.

Nothing here imports the cron jobs; the dependency direction is
``cron.jobs -> app.husky -> app.{config,models}``.
"""

from __future__ import annotations

from app.husky.archive import archive_raw
from app.husky.client import FetchResult, HuskyClient
from app.husky.normalize import (
    is_refunded,
    minor_units_to_euros,
    normalize_vat_fraction,
    parse_decimal,
    sum_discount_minor_units,
)

__all__ = [
    "HuskyClient",
    "FetchResult",
    "archive_raw",
    "minor_units_to_euros",
    "parse_decimal",
    "is_refunded",
    "normalize_vat_fraction",
    "sum_discount_minor_units",
]
