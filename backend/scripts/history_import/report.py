"""Plain-text run report for the history import (dry run and real run alike)."""

from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass

from app.models.enums import DispatchStatus
from app.money import cents_to_euro_str
from scripts.history_import.database import RestockWeek, WriteSummary
from scripts.history_import.plan import (
    PENDING_ORDER_MAX_AGE,
    UNDECIDED_FRIDGE_NAMES,
    Catalogue,
    DropReason,
    ImportPlan,
    Table,
    week_start_of,
)
from scripts.history_import.workbook import WorkbookHistory

TOP_DETAIL_COUNT = 10
# Order totals in the workbook carry float noise; a difference within one cent is a match.
ORDER_TOTAL_TOLERANCE_CENTS = 1


@dataclass(frozen=True)
class RunResult:
    history: WorkbookHistory
    plan: ImportPlan
    catalogue: Catalogue
    summary: WriteSummary
    restock_weeks: list[RestockWeek]


def render_report(result: RunResult) -> str:
    sections = [
        _workbook_section(result.history),
        _dispatch_section(result),
        _order_section(result),
        _target_section(result),
        _fridge_section(result),
        _blank_code_section(result),
        _dropped_section(result.plan),
        _collision_section(result.summary),
        _dispatch_reconciliation_section(result),
        _order_reconciliation_section(result.plan),
    ]
    return "\n\n".join(sections)


def _workbook_section(history: WorkbookHistory) -> str:
    delivery_dates = {row.delivery_date for row in history.dispatch_rows}
    return "\n".join(
        [
            "=== WORKBOOK ===",
            f"dispatch rows: {len(history.dispatch_rows)}",
            f"delivery days: {len(delivery_dates)}",
            f"delivery date range: {min(delivery_dates)} .. {max(delivery_dates)}",
            f"order headers: {len(history.order_headers)}",
            f"order lines: {len(history.order_lines)}",
            f"target rows: {len(history.targets)}",
        ]
    )


def _dispatch_section(result: RunResult) -> str:
    batches_by_status: Counter[str] = Counter()
    lines_by_status: Counter[str] = Counter()
    units_by_status: Counter[str] = Counter()
    for dispatch in result.plan.dispatches:
        batches_by_status[dispatch.status.value] += 1
        lines_by_status[dispatch.status.value] += len(dispatch.lines)
        units_by_status[dispatch.status.value] += sum(line.qty for line in dispatch.lines)
    lines = ["=== DISPATCHES (planned) ==="]
    for status, batch_count in sorted(batches_by_status.items()):
        lines.append(
            f"{status}: {batch_count} batches, {lines_by_status[status]} lines, "
            f"{units_by_status[status]} units"
        )
    saved_dispatches = [
        dispatch for dispatch in result.plan.dispatches if dispatch.status is DispatchStatus.saved
    ]
    for dispatch in saved_dispatches:
        saved_units = sum(line.qty for line in dispatch.lines)
        lines.append(f"  saved {dispatch.delivery_date}: {saved_units} units")
    summary = result.summary
    lines.append(
        f"written: {summary.dispatches_inserted} batches "
        f"({summary.dispatches_replaced} replaced), {summary.dispatch_lines_inserted} lines"
    )
    return "\n".join(lines)


def _order_section(result: RunResult) -> str:
    plan = result.plan
    orders_by_status: Counter[str] = Counter()
    lines_by_status: Counter[str] = Counter()
    for order in plan.orders:
        orders_by_status[order.status.value] += 1
        lines_by_status[order.status.value] += len(order.lines)
    lines = ["=== PURCHASE ORDERS (planned) ==="]
    for status, order_count in sorted(orders_by_status.items()):
        lines.append(f"{status}: {order_count} orders, {lines_by_status[status]} lines")
    summary = result.summary
    lines.extend(
        [
            (
                f"pending aged to received (delivery > {PENDING_ORDER_MAX_AGE.days} days ago): "
                f"{len(plan.orders_aged_to_received)}"
            ),
            f"expected delivery raised to order date: {len(plan.orders_delivery_date_clamped)}",
            f"negative received qty set to 0: {plan.order_lines_received_clamped}",
            (
                f"written: {summary.orders_inserted} orders ({summary.orders_replaced} replaced), "
                f"{summary.order_lines_inserted} lines"
            ),
            f"order_no_counters before: {summary.order_counters_before}",
            f"order_no_counters after:  {summary.order_counters_after}",
        ]
    )
    return "\n".join(lines)


def _target_section(result: RunResult) -> str:
    summary = result.summary
    return "\n".join(
        [
            "=== SNACK/DRINK TARGETS ===",
            f"planned: {len(result.plan.targets)}",
            f"written: {summary.targets_inserted} inserted, {summary.targets_updated} updated",
        ]
    )


def _fridge_section(result: RunResult) -> str:
    plan = result.plan
    placeholders_to_create = plan.placeholder_fridges_to_create(result.catalogue)
    lines = [
        "=== FRIDGES ===",
        f"inactive placeholders to create: {placeholders_to_create}",
        f"placeholders created this run: {result.summary.placeholder_fridges_created}",
        "unresolved fridge names (rows not imported):",
    ]
    for fridge_name, row_count in plan.unresolved_fridge_rows.most_common():
        note = UNDECIDED_FRIDGE_NAMES.get(fridge_name, "unknown name")
        lines.append(f"  {fridge_name!r}: {row_count} rows - {note}")
    for supplier_name, order_count in plan.unknown_supplier_orders.most_common():
        lines.append(f"unknown supplier {supplier_name!r}: {order_count} orders not imported")
    return "\n".join(lines)


def _blank_code_section(result: RunResult) -> str:
    plan = result.plan
    blank_row_count = sum(1 for row in result.history.dispatch_rows if not row.product_code)
    repaired_row_count = sum(repaired.row_count for repaired in plan.repaired_codes)
    unrepaired_names: Counter[str] = Counter()
    for dropped in plan.dropped_rows:
        if dropped.reason is DropReason.BLANK_CODE_NOT_REPAIRABLE:
            unrepaired_names[dropped.detail] += 1
    lines = [
        "=== BLANK PRODUCT CODES (dispatch rows) ===",
        f"blank-code rows: {blank_row_count}",
        f"repaired: {repaired_row_count} rows across {len(plan.repaired_codes)} product names",
        f"dropped: {sum(unrepaired_names.values())} rows",
    ]
    for product_name, row_count in unrepaired_names.most_common():
        lines.append(f"  dropped {product_name!r}: {row_count} rows")
    return "\n".join(lines)


def _dropped_section(plan: ImportPlan) -> str:
    counts: Counter[tuple[Table, DropReason]] = Counter()
    unknown_codes: Counter[str] = Counter()
    for dropped in plan.dropped_rows:
        counts[(dropped.table, dropped.reason)] += 1
        if dropped.reason is DropReason.UNKNOWN_PRODUCT:
            unknown_codes[f"{dropped.table}: {dropped.detail}"] += 1
    lines = ["=== DROPPED ROWS BY REASON ==="]
    for (table, reason), row_count in sorted(counts.items()):
        lines.append(f"{table} / {reason}: {row_count}")
    top_unknown_codes = unknown_codes.most_common(TOP_DETAIL_COUNT)
    for code_detail, row_count in top_unknown_codes:
        lines.append(f"  unknown product {code_detail}: {row_count} rows")
    return "\n".join(lines)


def _collision_section(summary: WriteSummary) -> str:
    lines = [f"=== COLLISIONS WITH APP-CREATED DATA (skipped): {len(summary.collisions)} ==="]
    for collision in summary.collisions:
        record = collision.record
        lines.append(
            f"{collision.kind} {record.key}: id {record.id}, status {record.status}, "
            f"{record.line_count} lines, {record.stock_movement_count} stock movements"
        )
    return "\n".join(lines)


def _dispatch_reconciliation_section(result: RunResult) -> str:
    dispatched_units_by_week: Counter[datetime.date] = Counter()
    for dispatch in result.plan.dispatches:
        if dispatch.status is not DispatchStatus.dispatched:
            continue
        week_start = week_start_of(dispatch.delivery_date)
        dispatched_units_by_week[week_start] += sum(line.qty for line in dispatch.lines)
    restock_by_week = {week.week_start: week for week in result.restock_weeks}
    lines = [
        "=== RECONCILIATION: dispatched units vs Husky restock 'added' units, per week ===",
        "week_start  dispatched  restock_added  restock_removed  added/dispatched",
    ]
    weeks = sorted(dispatched_units_by_week)
    for week_start in weeks:
        dispatched_units = dispatched_units_by_week[week_start]
        restock = restock_by_week.get(week_start)
        added_units = restock.added_units if restock else 0
        removed_units = restock.removed_units if restock else 0
        ratio = added_units / dispatched_units
        lines.append(
            f"{week_start}  {dispatched_units:>10}  {added_units:>13}  "
            f"{removed_units:>15}  {ratio:>16.2f}"
        )
    return "\n".join(lines)


def _order_reconciliation_section(plan: ImportPlan) -> str:
    """Workbook totals include qty <= 0 lines the import drops, so those orders differ."""
    orders_with_dropped_lines = set()
    for dropped in plan.dropped_rows:
        if dropped.table is Table.ORDER_LINES and dropped.reason is DropReason.NON_POSITIVE_QTY:
            orders_with_dropped_lines.add(dropped.detail)
    computed_total = sum(order.total_incl_vat for order in plan.orders)
    workbook_total = sum(order.workbook_total_incl_vat for order in plan.orders)
    explained_count = 0
    unexplained_differences = []
    for order in plan.orders:
        difference = order.total_incl_vat - order.workbook_total_incl_vat
        if abs(difference) <= ORDER_TOTAL_TOLERANCE_CENTS:
            continue
        if order.order_no in orders_with_dropped_lines:
            explained_count += 1
        else:
            unexplained_differences.append((abs(difference), order.order_no, difference))
    unexplained_differences.sort(reverse=True)
    lines = [
        "=== RECONCILIATION: PO totals incl. VAT (imported orders) ===",
        f"computed from imported lines: {cents_to_euro_str(computed_total)} EUR",
        f"workbook column:              {cents_to_euro_str(workbook_total)} EUR",
        f"difference:                   {cents_to_euro_str(computed_total - workbook_total)} EUR",
        f"orders differing, explained by dropped qty <= 0 lines: {explained_count}",
        f"orders differing, no dropped line: {len(unexplained_differences)}",
    ]
    largest_differences = unexplained_differences[:TOP_DETAIL_COUNT]
    for _size, order_no, difference in largest_differences:
        lines.append(f"  {order_no}: {cents_to_euro_str(difference)} EUR")
    return "\n".join(lines)
