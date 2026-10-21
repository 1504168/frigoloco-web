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
run never overlaps itself or stacks missed fires. At startup, every job whose
last successful ``sync_run`` is older than its interval (or that never ran) gets
its first fire moved to now, staggered by ``CATCH_UP_SPACING`` in list order. The
catch-up is the job's own scheduled entry, so ``max_instances=1`` still stops it
overlapping its next regular fire. Logs go to stdout. Each job is also runnable
standalone via ``python -m cron.jobs.<name>``.
"""

from __future__ import annotations

import datetime
import logging
import sys
from dataclasses import dataclass
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.util import undefined

from app.husky.sync import utcnow

from cron.catch_up import find_overdue_jobs
from cron.jobs import (
    catalogue_sync,
    partition_maintenance,
    recompute_scores,
    reviews_sync,
    snapshot_stock,
    sync_purchases,
    sync_restock,
)
from cron.sync_history import load_last_synced_by_job

logger = logging.getLogger("cron.scheduler")

TIMEZONE = "Europe/Brussels"
# Gap between catch-up starts so overdue jobs do not all hit Husky and the DB at once.
CATCH_UP_SPACING = datetime.timedelta(seconds=15)
QUARTER_HOUR = datetime.timedelta(minutes=15)
HOUR = datetime.timedelta(hours=1)
DAY = datetime.timedelta(days=1)
MONTH = datetime.timedelta(days=31)


@dataclass(frozen=True)
class ScheduledJob:
    """A job function, the cron trigger it fires on, and the gap between its fires."""

    id: str
    func: Callable[[], object]
    trigger: CronTrigger
    interval: datetime.timedelta


def _jobs() -> list[ScheduledJob]:
    # Order is the catch-up start order: catalogue first so event syncs find their
    # products, scores after the syncs they read.
    tz = TIMEZONE
    return [
        ScheduledJob(
            id="catalogue_sync",
            func=catalogue_sync.run,
            trigger=CronTrigger(hour="2", minute="0", timezone=tz),
            interval=DAY,
        ),
        ScheduledJob(
            id="snapshot_stock",
            func=snapshot_stock.run,
            trigger=CronTrigger(minute="*/15", timezone=tz),
            interval=QUARTER_HOUR,
        ),
        ScheduledJob(
            id="sync_purchases",
            func=sync_purchases.run,
            trigger=CronTrigger(minute="5", timezone=tz),
            interval=HOUR,
        ),
        ScheduledJob(
            id="sync_restock",
            func=sync_restock.run,
            trigger=CronTrigger(minute="10", timezone=tz),
            interval=HOUR,
        ),
        ScheduledJob(
            id="reviews_sync",
            func=reviews_sync.run,
            trigger=CronTrigger(hour="2", minute="15", timezone=tz),
            interval=DAY,
        ),
        ScheduledJob(
            id="recompute_scores",
            func=recompute_scores.run,
            trigger=CronTrigger(hour="2", minute="30", timezone=tz),
            interval=DAY,
        ),
        ScheduledJob(
            id="partition_maintenance",
            func=partition_maintenance.run,
            trigger=CronTrigger(day="1", hour="1", minute="0", timezone=tz),
            interval=MONTH,
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
    jobs = _jobs()
    catch_up_times = plan_catch_up_times(jobs, load_last_synced_by_job(), utcnow())
    for job in jobs:
        scheduler.add_job(
            _run_safely,
            trigger=job.trigger,
            args=[job.id, job.func],
            id=job.id,
            name=job.id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
            next_run_time=catch_up_times.get(job.id, undefined),
        )
        logger.info("registered job %s -> %s", job.id, job.trigger)
    return scheduler


def plan_catch_up_times(
    jobs: list[ScheduledJob],
    last_synced_by_job: dict[str, datetime.datetime],
    now: datetime.datetime,
) -> dict[str, datetime.datetime]:
    """First-fire time for each overdue job, keyed by job id; jobs not listed keep their trigger."""
    job_intervals = {job.id: job.interval for job in jobs}
    overdue_jobs = find_overdue_jobs(job_intervals, last_synced_by_job, now)
    catch_up_times = {}
    for position, overdue_job in enumerate(overdue_jobs):
        run_at = now + position * CATCH_UP_SPACING
        catch_up_times[overdue_job.job_id] = run_at
        logger.info(
            "catch-up: %s overdue (%s), runs at startup +%ss",
            overdue_job.job_id,
            overdue_job.describe_reason(now),
            int((run_at - now).total_seconds()),
        )
    return catch_up_times


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
