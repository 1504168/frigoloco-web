"""Gap-free, chunked windows for the incremental event syncs (purchases, restock, reviews).

A run starts at the earlier of its trailing window and the last successful window end
minus ``RESUME_OVERLAP``, so after any outage it covers everything since the last
success. The span is split into ``MAX_WINDOW_SPAN`` chunks run oldest first, each its
own fetch, short write transaction and ``sync_run`` row. A failing chunk stops the run,
so the next run resumes from the last chunk that succeeded.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.husky.sync import JobOutcome, clamp_report_to, utcnow

from cron.sync_history import load_last_synced_by_job

logger = logging.getLogger("cron.event_windows")

RESUME_OVERLAP = datetime.timedelta(hours=1)
# Husky has no pagination; 7-day windows are proven safe for every event endpoint.
MAX_WINDOW_SPAN = datetime.timedelta(days=7)

SyncWindowFn = Callable[[datetime.datetime, datetime.datetime], JobOutcome]


@dataclass(frozen=True)
class TimeWindow:
    start: datetime.datetime
    end: datetime.datetime


def run_event_sync(
    job: str,
    sync_window: SyncWindowFn,
    trailing_span: datetime.timedelta,
    window_from: datetime.datetime | None = None,
    window_to: datetime.datetime | None = None,
) -> JobOutcome:
    """Sync ``job`` over the resolved window in chunks; explicit bounds override the defaults."""
    window_end = clamp_report_to(window_to or utcnow())
    window_start = window_from or resolve_window_start(
        trailing_start=window_end - trailing_span,
        last_synced_until=load_last_synced_by_job().get(job),
    )
    windows = split_into_windows(window_start, window_end)
    total = JobOutcome()
    for position, window in enumerate(windows, start=1):
        logger.info(
            "%s: window %s/%s %s .. %s",
            job,
            position,
            len(windows),
            window.start.isoformat(),
            window.end.isoformat(),
        )
        outcome = sync_window(window.start, window.end)
        _add_outcome(total, outcome)
    return total


def resolve_window_start(
    trailing_start: datetime.datetime,
    last_synced_until: datetime.datetime | None,
) -> datetime.datetime:
    """Earlier of the trailing window start and the last successful window end minus overlap."""
    if last_synced_until is None:
        return trailing_start
    return min(trailing_start, last_synced_until - RESUME_OVERLAP)


def split_into_windows(
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[TimeWindow]:
    """Contiguous windows of at most ``MAX_WINDOW_SPAN`` covering ``start`` .. ``end``."""
    windows = []
    window_start = start
    while window_start < end:
        window_end = min(window_start + MAX_WINDOW_SPAN, end)
        windows.append(TimeWindow(window_start, window_end))
        window_start = window_end
    return windows


def _add_outcome(total: JobOutcome, outcome: JobOutcome) -> None:
    total.fetched += outcome.fetched
    total.upserted += outcome.upserted
    total.skipped += outcome.skipped
    total.unrepresentable += outcome.unrepresentable
    total.notes.extend(outcome.notes)
    total.blob_path = outcome.blob_path
