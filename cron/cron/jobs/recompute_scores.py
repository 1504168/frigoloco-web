"""recompute_scores - daily 02:30.

Thin wrapper that delegates to the backend scoring service
(``app.services.scoring_service.recompute_scores``) - the scoring math lives in
the backend and is NOT duplicated here (Criticizer finding S2-6). Each run stores
every scoring window (90, 180 and 365 days) so the Rating page has all three.

Legacy weights are read from the ``settings`` table by the service itself.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys

from app.db import SessionLocal
from app.services.scoring_service import SCORE_WINDOW_OPTIONS, recompute_scores

from cron.jobs._base import JobOutcome, SyncRunRecorder

logger = logging.getLogger("cron.jobs.recompute_scores")

JOB_NAME = "recompute_scores"


def run(as_of: datetime.date | None = None) -> JobOutcome:
    as_of = as_of or datetime.date.today()
    outcome = JobOutcome()
    with SyncRunRecorder(JOB_NAME, "product_scores") as recorder:
        for window_days in SCORE_WINDOW_OPTIONS:
            scored = _recompute_window(as_of, window_days)
            logger.info(
                "recompute_scores as_of=%s window_days=%s scored=%s",
                as_of,
                window_days,
                scored,
            )
            outcome.fetched += scored
            outcome.upserted += scored
        status = "success" if outcome.upserted else "empty"
        recorder.finish(status, outcome.fetched, outcome.upserted)
    return outcome


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Recompute product scores for every window via the backend service."
    )
    parser.add_argument("--as-of", dest="as_of", type=_parse_date, default=None)
    args = parser.parse_args(argv)
    outcome = run(args.as_of)
    print(f"scored={outcome.upserted}")
    return 0


def _recompute_window(as_of: datetime.date, window_days: int) -> int:
    session = SessionLocal()
    try:
        return recompute_scores(
            as_of=as_of,
            window_days=window_days,
            user_id=None,
            session=session,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _parse_date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
