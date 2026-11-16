"""Import the Forecasting workbook's history into the operational tables.

Sources (Excel tables in "Smart Fridge Forecasting Tool V5.xlsx"):

* GlobalDispatchHistoryTable (+ its summary table for save times) -> dispatches + dispatch_lines
* OrdersSummaryTable + OrdersLineItemsTable -> purchase_orders + purchase_order_lines
* Snacks_And_Drinks_Target_MapTable -> product_targets (upsert)

Re-runnable every week until Excel is retired: each delivery date / order number in
the workbook replaces the previously imported batch / order (rows marked by the
import system user), so edits made in Excel are picked up. App-created rows at the
same key are reported as collisions and never touched. No stock_movements are
written: this is a historical record, not a stock ledger.

Usage::

    python -u scripts/import_history.py --dry-run
    python -u scripts/import_history.py --workbook /path/to/Tool.xlsx
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

# Run as a file (python scripts/import_history.py): put the backend root on the path.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal, engine  # noqa: E402
from scripts.history_import.database import (  # noqa: E402
    ensure_dispatch_partitions,
    load_catalogue,
    load_weekly_restock_units,
    write_plan,
)
from scripts.history_import.plan import build_import_plan, week_start_of  # noqa: E402
from scripts.history_import.report import RunResult, render_report  # noqa: E402
from scripts.history_import.workbook import read_workbook_history  # noqa: E402

DEFAULT_WORKBOOK = Path.home() / "Downloads" / "Smart Fridge Forecasting Tool V5.xlsx"
BUSINESS_TIMEZONE = ZoneInfo("Europe/Brussels")
DAYS_TO_WEEK_END = datetime.timedelta(days=6)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    started = time.monotonic()
    database_url = engine.url
    _log(started, f"database {database_url.host}:{database_url.port}/{database_url.database}")
    _log(started, f"reading workbook {args.workbook}")
    history = read_workbook_history(args.workbook)
    _log(started, f"workbook read: {len(history.dispatch_rows)} dispatch rows")

    with SessionLocal() as session:
        catalogue = load_catalogue(session)
        plan = build_import_plan(history, catalogue, args.import_date)
        _log(started, f"plan built: {len(plan.dispatches)} batches, {len(plan.orders)} orders")
        has_unresolved_names = bool(plan.unresolved_fridge_rows or plan.unknown_supplier_orders)
        if has_unresolved_names and not args.dry_run and not args.skip_unresolved:
            print(
                "Unresolved fridge or supplier names (see --dry-run report). Map them in "
                "scripts/history_import/plan.py, or pass --skip-unresolved to leave their "
                "rows out.",
                file=sys.stderr,
            )
            return 1

        ensure_dispatch_partitions(plan)
        summary = write_plan(session, plan, catalogue)
        first_delivery_date = min(row.delivery_date for row in history.dispatch_rows)
        last_delivery_date = max(row.delivery_date for row in history.dispatch_rows)
        restock_weeks = load_weekly_restock_units(
            session=session,
            first_day=week_start_of(first_delivery_date),
            last_day=week_start_of(last_delivery_date) + DAYS_TO_WEEK_END,
        )
        if args.dry_run:
            session.rollback()
            _log(started, "DRY RUN: rolled back, nothing committed")
        else:
            session.commit()
            _log(started, "committed")

    result = RunResult(
        history=history,
        plan=plan,
        catalogue=catalogue,
        summary=summary,
        restock_weeks=restock_weeks,
    )
    print("\n" + render_report(result), flush=True)
    return 0


def _log(started: float, message: str) -> None:
    elapsed_seconds = time.monotonic() - started
    print(f"[{elapsed_seconds:6.1f}s] {message}", flush=True)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    today_in_brussels = datetime.datetime.now(BUSINESS_TIMEZONE).date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workbook",
        type=Path,
        default=DEFAULT_WORKBOOK,
        help="Path to the Forecasting workbook (.xlsx).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run every write inside a transaction, report, then roll back.",
    )
    parser.add_argument(
        "--skip-unresolved",
        action="store_true",
        help="Allow a real run to leave out rows of unmapped fridges or suppliers.",
    )
    parser.add_argument(
        "--import-date",
        type=datetime.date.fromisoformat,
        default=today_in_brussels,
        help="Reference date for ageing old pending POs (default: today, Brussels).",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
