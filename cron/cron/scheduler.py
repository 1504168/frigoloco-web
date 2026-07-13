"""APScheduler worker - the long-running cron container.

Runs the operational Husky jobs on Europe/Brussels wall-clock per the cron
catalogue in ``architecture/IMPLEMENTATION-BRIEF.md``:

    purchases   :05 hourly
    restock     :10 hourly
    snapshot    */15
    catalogue   02:00 daily
    reviews     02:15 daily
    scores      02:30 daily
    partitions  01:00 on the 1st of each month

Every job is registered with ``max_instances=1`` + ``coalesce=True`` so a slow
run never overlaps itself or stacks missed fires. Logs go to stdout. Each job is
also runnable standalone via ``python -m cron.jobs.<name>``.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from cron.jobs import (
    catalogue_sync,
    partition_maintenance,
    recompute_scores,
    reviews_sync,
    snapshot_stock,
    sync_purchases,
    sync_restock,
)

logger = logging.getLogger("cron.scheduler")

TIMEZONE = "Europe/Brussels"


@dataclass(frozen=True)
class ScheduledJob:
    """A job function plus the cron trigger it fires on."""

    id: str
    func: Callable[[], object]
    trigger: CronTrigger


def _jobs() -> list[ScheduledJob]:
    tz = TIMEZONE
    return [
        ScheduledJob("sync_purchases", sync_purchases.run, CronTrigger(minute="5", timezone=tz)),
        ScheduledJob("sync_restock", sync_restock.run, CronTrigger(minute="10", timezone=tz)),
        ScheduledJob("snapshot_stock", snapshot_stock.run, CronTrigger(minute="*/15", timezone=tz)),
        ScheduledJob("catalogue_sync", catalogue_sync.run, CronTrigger(hour="2", minute="0", timezone=tz)),
        ScheduledJob("reviews_sync", reviews_sync.run, CronTrigger(hour="2", minute="15", timezone=tz)),
        ScheduledJob("recompute_scores", recompute_scores.run, CronTrigger(hour="2", minute="30", timezone=tz)),
        ScheduledJob(
            "partition_maintenance",
            partition_maintenance.run,
            CronTrigger(day="1", hour="1", minute="0", timezone=tz),
        ),
    ]


def _run_safely(job_id: str, func: Callable[[], object]) -> None:
    """Wrap a job so an exception is logged but never kills the scheduler."""
    try:
        func()
    except Exception:
        logger.exception("job %s failed", job_id)


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    for job in _jobs():
        scheduler.add_job(
            _run_safely,
            trigger=job.trigger,
            args=[job.id, job.func],
            id=job.id,
            name=job.id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        logger.info("registered job %s -> %s", job.id, job.trigger)
    return scheduler


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    scheduler = build_scheduler()
    logger.info("starting FrigoLoco cron scheduler (%s)", TIMEZONE)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
