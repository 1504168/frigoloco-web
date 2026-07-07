"""Database partition maintenance (D1.2) — importable domain layer.

``dispatch_lines``, ``sales_events`` and ``restock_events`` are RANGE-partitioned
monthly on their date key. An insert dated beyond the last pre-created partition
fails with *"no partition of relation ... found for row"*. The schema function
:sql:`create_next_month_event_partitions()` idempotently ensures the CURRENT and
NEXT month's partitions exist for all three tables.

This module is the single importable entry point the monthly APScheduler job
(``cron.jobs.partition_maintenance``) — and any operator — calls, mirroring the
Husky ``cron -> backend`` thin-wrapper pattern. It is DB-only: no vendor call.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field

from sqlalchemy import text

from app.db import SessionLocal

logger = logging.getLogger("maintenance.partitions")

# Event tables whose monthly partitions the schema function maintains, plus
# dispatch_lines. Used only to VERIFY/REPORT which partitions now exist.
_PARTITIONED_TABLES: tuple[str, ...] = ("sales_events", "restock_events", "dispatch_lines")


@dataclass
class PartitionMaintenanceOutcome:
    """What a maintenance run ensured — for CLI output and test assertions."""

    months: list[str] = field(default_factory=list)  # e.g. ["2026_07", "2026_08"]
    ensured_partitions: list[str] = field(default_factory=list)


def _month_suffixes(today: datetime.date) -> list[str]:
    """Return the ``YYYY_MM`` suffixes for the current and next calendar month."""
    first_of_this = today.replace(day=1)
    # Day 28 + 4 days always lands in the next month; truncate back to its first.
    first_of_next = (first_of_this + datetime.timedelta(days=32)).replace(day=1)
    return [first_of_this.strftime("%Y_%m"), first_of_next.strftime("%Y_%m")]


def run_partition_maintenance(
    today: datetime.date | None = None,
) -> PartitionMaintenanceOutcome:
    """Ensure current+next month partitions exist for all range-partitioned tables.

    Idempotent: the schema function uses ``CREATE TABLE IF NOT EXISTS`` per
    partition, so re-running is a safe no-op. Returns the partitions that exist
    for the target months afterward (for logging / assertions).
    """
    today = today or datetime.date.today()
    months = _month_suffixes(today)
    outcome = PartitionMaintenanceOutcome(months=months)
    session = SessionLocal()
    try:
        session.execute(text("SELECT create_next_month_event_partitions()"))
        session.commit()
        # Report which of the expected partitions now exist (idempotency proof).
        expected = [
            f"{table}_{suffix}" for table in _PARTITIONED_TABLES for suffix in months
        ]
        rows = session.execute(
            text(
                "SELECT relname FROM pg_class "
                "WHERE relkind = 'r' AND relname = ANY(:names) "
                "ORDER BY relname"
            ),
            {"names": expected},
        ).scalars()
        outcome.ensured_partitions = list(rows)
    finally:
        session.close()
    logger.info(
        "partition maintenance: months=%s ensured=%d partitions",
        months, len(outcome.ensured_partitions),
    )
    return outcome
