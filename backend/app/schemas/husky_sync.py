"""Schemas for the Husky sync API (``/api/v1/sync``).

The sync endpoints trigger the domain sync functions in :mod:`app.husky.sync`
via FastAPI ``BackgroundTasks`` and expose the ``sync_run`` checkpoint history.
"""

from __future__ import annotations

import datetime
from typing import Literal

from app.schemas.masters import ApiModel

# The feeds a client may trigger. ``all`` runs every feed sequentially.
# purchases/restock/reviews are event feeds pulled over a trailing 48h window.
SyncFeed = Literal[
    "catalogue",
    "prices",
    "purchases",
    "restock",
    "reviews",
    "stock",
    "all",
]


class SyncTriggerResponse(ApiModel):
    """Returned immediately when a sync is scheduled — carries the checkpoint id."""

    sync_run_id: int
    feed: SyncFeed
    endpoint: str
    status: str  # always 'running' at trigger time
    window_from: datetime.datetime | None = None
    window_to: datetime.datetime | None = None


class SyncRunRead(ApiModel):
    """A single ``sync_run`` checkpoint row."""

    id: int
    job: str
    endpoint: str
    window_from: datetime.datetime | None
    window_to: datetime.datetime | None
    status: str
    records_fetched: int
    records_upserted: int
    blob_path: str | None
    error: str | None
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
