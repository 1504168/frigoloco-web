"""partition_maintenance - monthly, 1st of month 01:00 Europe/Brussels.

Thin scheduler/CLI wrapper. The partition-maintenance logic lives in
:func:`app.maintenance.run_partition_maintenance`, which calls the schema
function ``create_next_month_event_partitions()`` to ensure the current AND next
month's partitions exist for ``sales_events``, ``restock_events`` and
``dispatch_lines`` before any insert can land in them.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.maintenance import PartitionMaintenanceOutcome, run_partition_maintenance

logger = logging.getLogger("cron.jobs.partition_maintenance")

JOB_NAME = "partition_maintenance"


def run() -> PartitionMaintenanceOutcome:
    """Ensure current+next month partitions exist. Returns the outcome."""
    return run_partition_maintenance()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Ensure current+next month table partitions exist (idempotent)."
    )
    parser.parse_args(argv)
    outcome = run()
    print(f"months: {', '.join(outcome.months)}")
    print(f"partitions ensured ({len(outcome.ensured_partitions)}):")
    for name in outcome.ensured_partitions:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
