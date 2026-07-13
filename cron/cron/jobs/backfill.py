"""backfill - CLI-only resumable historical pull.

Walks an ``--endpoint`` over ``--from``/``--to`` in 7-day chunks, delegating each
chunk to the matching incremental sync job (so raw-first archive + ``sync_run``
bookkeeping + idempotent upserts are reused). Behaviour:

* **Resumable** - a chunk whose ``sync_run`` already recorded ``success``/``empty``
  for the same job+endpoint+window is skipped.
* **Self-healing** - a chunk that raises is halved and each half retried, down to
  a 1-day floor, isolating a poison window without failing the whole run.
* ``--dry-run`` prints the window plan (and which windows would be skipped)
  without calling the vendor or writing anything.

The API has no pagination and no documented rate limit; the client throttle plus
7-day windows keep a multi-year backfill well under a few hundred requests.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from sqlalchemy import select

from app.db import SessionLocal
from app.models import SyncRun

from cron.jobs import reviews_sync, sync_purchases, sync_restock
from cron.jobs._base import JobOutcome

logger = logging.getLogger("cron.jobs.backfill")

JOB_NAME = "backfill"
_CHUNK = datetime.timedelta(days=7)
_MIN_CHUNK = datetime.timedelta(days=1)
_RESUMABLE_STATUSES = ("success", "empty")

RunFn = Callable[[datetime.datetime, datetime.datetime], JobOutcome]


@dataclass(frozen=True)
class EndpointSpec:
    """Binds a backfill endpoint name to its incremental sync job."""

    run: RunFn
    job: str
    endpoint: str


_ENDPOINTS: dict[str, EndpointSpec] = {
    "purchases": EndpointSpec(sync_purchases.run, "sync_purchases", "purchases"),
    "restock": EndpointSpec(sync_restock.run, "sync_restock", "restock"),
    "reviews": EndpointSpec(reviews_sync.run, "reviews_sync", "productreview"),
    "productreview": EndpointSpec(reviews_sync.run, "reviews_sync", "productreview"),
}


def _chunks(window_from: datetime.datetime, window_to: datetime.datetime) -> Iterator[tuple[datetime.datetime, datetime.datetime]]:
    start = window_from
    while start < window_to:
        end = min(start + _CHUNK, window_to)
        yield start, end
        start = end


def _already_done(spec: EndpointSpec, cfrom: datetime.datetime, cto: datetime.datetime) -> bool:
    session = SessionLocal()
    try:
        row = session.execute(
            select(SyncRun.id)
            .where(
                SyncRun.job == spec.job,
                SyncRun.endpoint == spec.endpoint,
                SyncRun.window_from == cfrom,
                SyncRun.window_to == cto,
                SyncRun.status.in_(_RESUMABLE_STATUSES),
            )
            .limit(1)
        ).first()
        return row is not None
    finally:
        session.close()


def _run_chunk(spec: EndpointSpec, cfrom: datetime.datetime, cto: datetime.datetime) -> JobOutcome:
    """Run a chunk, halving the window and retrying on failure (1-day floor)."""
    try:
        return spec.run(cfrom, cto)
    except Exception as exc:
        if (cto - cfrom) <= _MIN_CHUNK:
            logger.error("chunk %s..%s failed at floor: %s", cfrom, cto, exc)
            raise
        mid = cfrom + (cto - cfrom) / 2
        logger.warning("chunk %s..%s failed (%s); halving at %s", cfrom, cto, exc, mid)
        left = _run_chunk(spec, cfrom, mid)
        right = _run_chunk(spec, mid, cto)
        return JobOutcome(
            fetched=left.fetched + right.fetched,
            upserted=left.upserted + right.upserted,
            skipped=left.skipped + right.skipped,
        )


def run(
    endpoint: str,
    window_from: datetime.datetime,
    window_to: datetime.datetime,
    dry_run: bool = False,
) -> JobOutcome:
    spec = _ENDPOINTS.get(endpoint.lower())
    if spec is None:
        raise ValueError(f"unknown endpoint {endpoint!r}; choose from {sorted(_ENDPOINTS)}")

    total = JobOutcome()
    planned = skipped = executed = 0
    for cfrom, cto in _chunks(window_from, window_to):
        planned += 1
        done = _already_done(spec, cfrom, cto)
        if dry_run:
            marker = "SKIP (already success/empty)" if done else "RUN"
            logger.info("[dry-run] %s %s..%s -> %s", spec.endpoint, cfrom.date(), cto.date(), marker)
            print(f"{spec.endpoint} {cfrom.isoformat()} .. {cto.isoformat()} -> {marker}")
            if done:
                skipped += 1
            continue
        if done:
            skipped += 1
            logger.info("skip %s %s..%s (already done)", spec.endpoint, cfrom, cto)
            continue
        outcome = _run_chunk(spec, cfrom, cto)
        executed += 1
        total.fetched += outcome.fetched
        total.upserted += outcome.upserted
        total.skipped += outcome.skipped

    total.notes.append(f"planned={planned} executed={executed} resumable_skipped={skipped} dry_run={dry_run}")
    logger.info("backfill %s: %s", spec.endpoint, total.notes[-1])
    return total


def _parse_dt(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Resumable historical Husky backfill (7-day chunks).")
    parser.add_argument("--endpoint", required=True, choices=sorted(_ENDPOINTS))
    parser.add_argument("--from", dest="window_from", required=True, type=_parse_dt)
    parser.add_argument("--to", dest="window_to", required=True, type=_parse_dt)
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    args = parser.parse_args(argv)
    outcome = run(args.endpoint, args.window_from, args.window_to, args.dry_run)
    print("; ".join(outcome.notes))
    print(f"fetched={outcome.fetched} upserted={outcome.upserted} skipped={outcome.skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
