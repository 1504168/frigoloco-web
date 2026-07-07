"""catalogue_sync — daily 02:00.

Thin scheduler/CLI wrapper. The Husky master-catalogue sync logic lives in
:func:`app.husky.sync.sync_catalogue` (shared with the FastAPI sync API).
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.husky.sync import JobOutcome, sync_catalogue

logger = logging.getLogger("cron.jobs.catalogue_sync")

JOB_NAME = "catalogue_sync"


def run() -> JobOutcome:
    """Sync the full master catalogue. Returns the aggregate outcome."""
    return sync_catalogue()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Sync Husky master catalogue.")
    parser.parse_args(argv)
    outcome = run()
    for note in outcome.notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
