"""reviews_sync — daily 02:15.

Thin scheduler/CLI wrapper. The Husky ``/productreview`` -> ``product_reviews``
sync logic lives in :func:`app.husky.sync.sync_reviews_window` (shared with the
FastAPI sync API and the backfill driver).
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys

from app.husky.sync import JobOutcome, sync_reviews_window

logger = logging.getLogger("cron.jobs.reviews_sync")

JOB_NAME = "reviews_sync"


def run(
    window_from: datetime.datetime | None = None,
    window_to: datetime.datetime | None = None,
) -> JobOutcome:
    return sync_reviews_window(window_from, window_to)


def _parse_dt(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Sync Husky product reviews.")
    parser.add_argument("--from", dest="window_from", type=_parse_dt, default=None)
    parser.add_argument("--to", dest="window_to", type=_parse_dt, default=None)
    args = parser.parse_args(argv)
    outcome = run(args.window_from, args.window_to)
    print(f"fetched={outcome.fetched} upserted={outcome.upserted} skipped={outcome.skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
