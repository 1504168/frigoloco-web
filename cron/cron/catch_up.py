"""Startup catch-up: find scheduled jobs whose last successful run is older than their interval."""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class OverdueJob:
    """A job to run at startup, with the timestamp that made it overdue (None = never ran)."""

    job_id: str
    last_synced_at: datetime.datetime | None
    interval: datetime.timedelta

    def describe_reason(self, now: datetime.datetime) -> str:
        if self.last_synced_at is None:
            return "no successful sync_run recorded"
        age = now - self.last_synced_at
        last_synced = self.last_synced_at.isoformat()
        return f"last synced {last_synced} ({age} ago) > interval {self.interval}"


def find_overdue_jobs(
    job_intervals: dict[str, datetime.timedelta],
    last_synced_by_job: dict[str, datetime.datetime],
    now: datetime.datetime,
) -> list[OverdueJob]:
    """Jobs (in ``job_intervals`` order) that never ran or ran longer than one interval ago."""
    overdue_jobs = []
    for job_id, interval in job_intervals.items():
        last_synced_at = last_synced_by_job.get(job_id)
        never_ran = last_synced_at is None
        if never_ran or now - last_synced_at > interval:
            overdue_jobs.append(OverdueJob(job_id, last_synced_at, interval))
    return overdue_jobs
