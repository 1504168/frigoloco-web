"""sync_restock - hourly :10.

Thin scheduler/CLI wrapper. The Husky ``/restock`` -> ``restock_events`` sync
logic lives in :func:`app.husky.sync.sync_restock_window` (shared with the
FastAPI sync API and the backfill driver).
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys

from app.husky.sync import JobOutcome, sync_restock_window

logger = logging.getLogger("cron.jobs.sync_restock")

JOB_NAME = "sync_restock"


def run(
    window_from: datetime.datetime | None = None,
    window_to: datetime.datetime | None = None,
) -> JobOutcome:
    return sync_restock_window(window_from, window_to)


def _parse_dt(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Sync Husky restock into restock_events.")
    parser.add_argument("--from", dest="window_from", type=_parse_dt, default=None)
    parser.add_argument("--to", dest="window_to", type=_parse_dt, default=None)
    args = parser.parse_args(argv)
    outcome = run(args.window_from, args.window_to)
    print(
        f"fetched={outcome.fetched} upserted={outcome.upserted} "
        f"skipped={outcome.skipped} unchanged_unrepresentable={outcome.unrepresentable}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
