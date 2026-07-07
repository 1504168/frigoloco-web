"""Shared job scaffolding — RE-EXPORT SHIM.

The sync/transform logic and its scaffolding (``sync_run`` bookkeeping, DB
resolvers, the stub-product resolver) were relocated to the backend package
:mod:`app.husky.sync` (work-order D5) so the FastAPI sync API and these cron
jobs share one implementation. The dependency only flows ``cron -> backend``
(never the reverse), so this module simply re-exports the names cron jobs and
tests have always imported from ``cron.jobs._base``.
"""

from __future__ import annotations

from app.husky.sync import (
    REPORT_LAG,
    UNCATEGORISED_NAME,
    UNKNOWN_PRODUCT_CODE,
    JobOutcome,
    ProductResolver,
    SyncRunRecorder,
    clamp_report_to,
    effective_product_code,
    load_fridge_index,
    load_product_index,
    resolve_fridge,
    utcnow,
)

__all__ = [
    "REPORT_LAG",
    "UNCATEGORISED_NAME",
    "UNKNOWN_PRODUCT_CODE",
    "JobOutcome",
    "ProductResolver",
    "SyncRunRecorder",
    "clamp_report_to",
    "effective_product_code",
    "load_fridge_index",
    "load_product_index",
    "resolve_fridge",
    "utcnow",
]
