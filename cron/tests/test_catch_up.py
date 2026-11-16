"""Startup catch-up planning: which jobs run immediately and when. No DB or scheduler start."""

from __future__ import annotations

import datetime

from cron.catch_up import find_overdue_jobs
from cron.scheduler import CATCH_UP_SPACING, _jobs, plan_catch_up_times

NOW = datetime.datetime(2026, 10, 21, 9, 0, tzinfo=datetime.timezone.utc)
HOUR = datetime.timedelta(hours=1)


def test_job_synced_within_interval_is_not_overdue():
    last_synced_by_job = {"sync_purchases": NOW - datetime.timedelta(minutes=40)}

    overdue_jobs = find_overdue_jobs({"sync_purchases": HOUR}, last_synced_by_job, NOW)

    assert overdue_jobs == []


def test_job_older_than_interval_is_overdue_with_its_last_sync():
    last_synced_at = NOW - datetime.timedelta(hours=3)

    overdue_jobs = find_overdue_jobs(
        {"sync_purchases": HOUR},
        {"sync_purchases": last_synced_at},
        NOW,
    )

    assert [job.job_id for job in overdue_jobs] == ["sync_purchases"]
    assert overdue_jobs[0].last_synced_at == last_synced_at
    assert "interval 1:00:00" in overdue_jobs[0].describe_reason(NOW)


def test_job_that_never_ran_is_overdue():
    overdue_jobs = find_overdue_jobs({"partition_maintenance": HOUR}, {}, NOW)

    assert overdue_jobs[0].last_synced_at is None
    assert overdue_jobs[0].describe_reason(NOW) == "no successful sync_run recorded"


def test_catch_up_times_are_staggered_in_job_list_order():
    fresh_jobs = {
        "snapshot_stock": NOW,
        "sync_restock": NOW,
        "low_stock_check": NOW,
    }

    catch_up_times = plan_catch_up_times(_jobs(), fresh_jobs, NOW)

    assert list(catch_up_times) == [
        "catalogue_sync",
        "sync_purchases",
        "reviews_sync",
        "recompute_scores",
        "partition_maintenance",
    ]
    assert catch_up_times["catalogue_sync"] == NOW
    assert catch_up_times["sync_purchases"] == NOW + CATCH_UP_SPACING
    assert catch_up_times["partition_maintenance"] == NOW + 4 * CATCH_UP_SPACING


def test_no_catch_up_when_every_job_is_fresh():
    every_job_fresh = {job.id: NOW for job in _jobs()}

    assert plan_catch_up_times(_jobs(), every_job_fresh, NOW) == {}
