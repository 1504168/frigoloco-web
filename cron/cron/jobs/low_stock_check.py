"""low_stock_check - hourly.

Opens one ``low_stock`` alert per product whose warehouse stock is below its
``min_stock_qty``, refreshes the ones still low and resolves the ones that
recovered. The rule lives in ``app.services.low_stock_service``.
"""

from __future__ import annotations

import logging
import sys

from app.db import SessionLocal
from app.services.low_stock_service import LowStockRefreshOutcome, refresh_low_stock_alerts

from cron.jobs._base import SyncRunRecorder

logger = logging.getLogger("cron.jobs.low_stock_check")

JOB_NAME = "low_stock_check"
ENDPOINT = "low_stock"


def run() -> LowStockRefreshOutcome:
    with SyncRunRecorder(JOB_NAME, ENDPOINT) as recorder:
        outcome = _refresh_alerts()
        logger.info(
            "low_stock_check opened=%s updated=%s resolved=%s",
            outcome.opened,
            outcome.updated,
            outcome.resolved,
        )
        alerts_written = outcome.opened + outcome.updated + outcome.resolved
        status = "success" if alerts_written else "empty"
        recorder.finish(status, alerts_written, alerts_written)
    return outcome


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    outcome = run()
    print(f"opened={outcome.opened} updated={outcome.updated} resolved={outcome.resolved}")
    return 0


def _refresh_alerts() -> LowStockRefreshOutcome:
    with SessionLocal() as session, session.begin():
        return refresh_low_stock_alerts(session)


if __name__ == "__main__":
    raise SystemExit(main())
