"""Reads of the ``sync_run`` history that the scheduler and the event syncs plan from."""

from __future__ import annotations

import datetime

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.sync import SyncRun

SUCCESSFUL_RUN_STATUSES = ("success", "empty")


def load_last_synced_by_job() -> dict[str, datetime.datetime]:
    """Latest successful sync_run per job, keyed by job name."""
    # window_to (when set) is how fresh the synced data is, so a recent backfill of an
    # old window does not count as a recent run.
    synced_until = func.coalesce(SyncRun.window_to, SyncRun.started_at)
    query = (
        select(SyncRun.job, func.max(synced_until))
        .where(SyncRun.status.in_(SUCCESSFUL_RUN_STATUSES))
        .group_by(SyncRun.job)
    )
    with SessionLocal() as session:
        rows = session.execute(query).all()
    return dict(rows)
