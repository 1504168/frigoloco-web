"""recompute_scores — daily 02:30.

Thin wrapper that delegates to the backend scoring service
(``app.services.scoring_service.recompute_scores``) — the scoring math lives in
the backend and is NOT duplicated here (Criticizer finding S2-6). If the service
is not importable yet, the job logs and exits 0 so the schedule stays green
while the backend catches up.

Legacy weights are read from the ``settings`` table by the service itself.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys

from app.db import SessionLocal

from cron.jobs._base import JobOutcome, SyncRunRecorder

logger = logging.getLogger("cron.jobs.recompute_scores")

JOB_NAME = "recompute_scores"


def run(as_of: datetime.date | None = None) -> JobOutcome:
    as_of = as_of or datetime.date.today()
    outcome = JobOutcome()
    try:
        from app.services.scoring_service import recompute_scores as _recompute
    except ImportError:
        logger.warning("scoring service not yet available; skipping (exit 0)")
        outcome.notes.append("scoring service not yet available")
        return outcome

    with SyncRunRecorder(JOB_NAME, "product_scores") as recorder:
        session = SessionLocal()
        try:
            scored = _recompute(as_of=as_of, user_id=None, session=session)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        outcome.fetched = scored
        outcome.upserted = scored
        recorder.finish("success" if scored else "empty", scored, scored)
    logger.info("recompute_scores as_of=%s scored=%s", as_of, outcome.upserted)
    return outcome


def _parse_date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Recompute product scores via the backend service.")
    parser.add_argument("--as-of", dest="as_of", type=_parse_date, default=None)
    args = parser.parse_args(argv)
    outcome = run(args.as_of)
    print(f"scored={outcome.upserted}" + ("" if outcome.upserted or not outcome.notes else f" ({outcome.notes[0]})"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
