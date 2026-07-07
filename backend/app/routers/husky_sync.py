"""Husky sync API — trigger syncs and read the checkpoint history.

* ``POST /api/v1/sync/husky/{feed}`` — schedule a sync of ``feed`` via
  ``BackgroundTasks``; the ``sync_run`` checkpoint row is created synchronously
  so its id is returned immediately while the work runs in the background.
* ``GET  /api/v1/sync/runs?endpoint&limit`` — recent ``sync_run`` checkpoints.

All sync logic lives in :mod:`app.husky.sync`; this router only maps a feed to
its domain function and manages the background scheduling + checkpoint reads.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Callable

from fastapi import BackgroundTasks, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.husky.sync import (
    JobOutcome,
    TRAILING_EVENT_WINDOW,
    clamp_report_to,
    create_sync_run,
    snapshot_stock,
    sync_all,
    sync_catalogue,
    sync_prices,
    sync_purchases_window,
    sync_restock_window,
    sync_reviews_window,
    utcnow,
)
from app.models import SyncRun
from app.schemas.husky_sync import SyncFeed, SyncRunRead, SyncTriggerResponse
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination

logger = logging.getLogger("husky.sync.api")

router = make_router(prefix="/api/v1/sync", tags=["sync"])


@dataclass(frozen=True)
class _FeedPlan:
    """Resolved sync plan for one feed: bookkeeping labels + the run callable."""

    job: str
    endpoint: str
    window_from: datetime.datetime | None
    window_to: datetime.datetime | None
    run: Callable[[int], JobOutcome]  # accepts the pre-created run_id


def _event_window() -> tuple[datetime.datetime, datetime.datetime]:
    """Trailing 48h window (clamped for the vendor's 5-minute report lag)."""
    window_to = clamp_report_to(utcnow())
    return window_to - TRAILING_EVENT_WINDOW, window_to


def _plan_for_feed(feed: SyncFeed) -> _FeedPlan:
    """Map a feed name to its checkpoint labels and background run callable."""
    if feed == "catalogue":
        return _FeedPlan("catalogue_sync", "catalogue", None, None,
                         lambda run_id: sync_catalogue(run_id=run_id))
    if feed == "prices":
        return _FeedPlan("catalogue_sync", "fridgeproductprice", None, None,
                         lambda run_id: sync_prices(run_id=run_id))
    if feed == "stock":
        return _FeedPlan("snapshot_stock", "stock_current", None, None,
                         lambda run_id: snapshot_stock(run_id=run_id))
    if feed == "all":
        return _FeedPlan("sync_all", "all", None, None,
                         lambda run_id: sync_all(run_id=run_id))
    if feed == "purchases":
        wfrom, wto = _event_window()
        return _FeedPlan("sync_purchases", "purchases", wfrom, wto,
                         lambda run_id: sync_purchases_window(wfrom, wto, run_id=run_id))
    if feed == "restock":
        wfrom, wto = _event_window()
        return _FeedPlan("sync_restock", "restock", wfrom, wto,
                         lambda run_id: sync_restock_window(wfrom, wto, run_id=run_id))
    if feed == "reviews":
        wfrom, wto = _event_window()
        return _FeedPlan("reviews_sync", "productreview", wfrom, wto,
                         lambda run_id: sync_reviews_window(wfrom, wto, run_id=run_id))
    raise api_error(422, "validation_error", f"Unknown sync feed: {feed}", {"feed": feed})


def _run_background(plan: _FeedPlan, run_id: int) -> None:
    """Execute the sync; the domain function records success/failure on the row."""
    try:
        plan.run(run_id)
    except Exception:  # pragma: no cover - failure already recorded on the row
        logger.exception("background sync failed: feed job=%s run_id=%s", plan.job, run_id)


@router.post("/husky/{feed}", response_model=SyncTriggerResponse)
def trigger_sync(
    feed: SyncFeed,
    background_tasks: BackgroundTasks,
) -> SyncTriggerResponse:
    """Schedule a sync of ``feed`` and return its ``sync_run`` id immediately."""
    plan = _plan_for_feed(feed)
    run_id = create_sync_run(plan.job, plan.endpoint, plan.window_from, plan.window_to)
    background_tasks.add_task(_run_background, plan, run_id)
    return SyncTriggerResponse(
        sync_run_id=run_id,
        feed=feed,
        endpoint=plan.endpoint,
        status="running",
        window_from=plan.window_from,
        window_to=plan.window_to,
    )


@router.get("/runs", response_model=Page[SyncRunRead])
def list_sync_runs(
    page: PaginationParams = Depends(pagination),
    endpoint: str | None = Query(default=None, description="Filter by sync_run.endpoint"),
    session: Session = Depends(get_db),
) -> Page[SyncRunRead]:
    """Recent ``sync_run`` checkpoints, newest first (optionally by endpoint)."""
    stmt = select(SyncRun)
    count_stmt = select(func.count()).select_from(SyncRun)
    if endpoint:
        stmt = stmt.where(SyncRun.endpoint == endpoint)
        count_stmt = count_stmt.where(SyncRun.endpoint == endpoint)
    total = session.execute(count_stmt).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(SyncRun.id.desc()).limit(page.limit).offset(page.offset)
        )
        .scalars()
        .all()
    )
    return Page(
        items=[SyncRunRead.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )
