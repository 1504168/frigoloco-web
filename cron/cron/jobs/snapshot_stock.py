"""snapshot_stock - every 15 min.

Thin scheduler/CLI wrapper. The Husky ``/stock/current`` -> ``fridge_stock``
refresh logic lives in :func:`app.husky.sync.snapshot_stock` (shared with the
FastAPI sync API). ``fridge_stock`` keeps only the LATEST state - one row per
fridge x product, mark-and-swept each run - not a history of snapshots.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.husky.sync import JobOutcome
from app.husky.sync import snapshot_stock as _snapshot_stock

logger = logging.getLogger("cron.jobs.snapshot_stock")

JOB_NAME = "snapshot_stock"


def run() -> JobOutcome:
    return _snapshot_stock()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Refresh fridge_stock from Husky current stock.")
    parser.parse_args(argv)
    outcome = run()
    print(f"fetched={outcome.fetched} upserted={outcome.upserted} skipped={outcome.skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
