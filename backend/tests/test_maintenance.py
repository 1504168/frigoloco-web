"""Live-DB tests for partition maintenance (D1.2, residual finding #4).

Two tiers:

* ``run_partition_maintenance`` (the entry point the monthly cron job calls)
  ensures the current AND next month's partitions exist for all three
  range-partitioned tables, and is idempotent (safe to re-run).
* The underlying schema building block actually CREATES a partition when one is
  missing and stays a no-op on re-run — proven inside a rolled-back transaction
  (DDL is transactional in PostgreSQL) so no artifact leaks into the DB.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db import engine
from app.maintenance import run_partition_maintenance

_PARTITIONED_TABLES = ("sales_events", "restock_events", "dispatch_lines")


def test_run_partition_maintenance_is_idempotent() -> None:
    first = run_partition_maintenance()
    second = run_partition_maintenance()

    assert first.months == second.months
    assert len(first.months) == 2  # current + next month
    expected = {
        f"{table}_{suffix}"
        for table in _PARTITIONED_TABLES
        for suffix in first.months
    }
    # Every current+next month partition exists for all three tables …
    assert set(first.ensured_partitions) == expected
    # … and a second run produces the identical set (no duplicates, no errors).
    assert set(second.ensured_partitions) == expected


def test_create_partition_for_missing_future_month_is_idempotent() -> None:
    """The schema function CREATES a missing partition and no-ops on re-run.

    Runs inside a transaction that is rolled back, so the far-future partition
    never persists (DDL participates in the transaction in PostgreSQL).
    """
    month_start = "2029-06-01"
    dispatch_part = "dispatch_lines_2029_06"
    sales_part = "sales_events_2029_06"

    connection = engine.connect()
    trans = connection.begin()
    try:
        def exists(name: str) -> bool:
            return (
                connection.execute(
                    text("SELECT 1 FROM pg_class WHERE relkind = 'r' AND relname = :n"),
                    {"n": name},
                ).first()
                is not None
            )

        # Pre-condition: this far-future month is beyond the pre-created range.
        assert not exists(dispatch_part)
        assert not exists(sales_part)

        # First call creates them.
        connection.execute(
            text("SELECT create_dispatch_line_partition_for_month(:m)"), {"m": month_start}
        )
        connection.execute(
            text("SELECT create_event_partitions_for_month(:m)"), {"m": month_start}
        )
        assert exists(dispatch_part)
        assert exists(sales_part)

        # Second call is a no-op (CREATE TABLE IF NOT EXISTS) — no error, still one.
        connection.execute(
            text("SELECT create_dispatch_line_partition_for_month(:m)"), {"m": month_start}
        )
        connection.execute(
            text("SELECT create_event_partitions_for_month(:m)"), {"m": month_start}
        )
        assert exists(dispatch_part)
        assert exists(sales_part)
    finally:
        trans.rollback()  # discard the far-future partitions
        connection.close()
