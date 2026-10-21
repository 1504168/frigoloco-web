"""Turn the workbook rows into an import plan: pure mapping, no database access.

Every rule that decides what a workbook row becomes lives here (fridge mapping,
product resolution, blank-code repair, batch status, PO status ageing, targets),
so the rules are unit-testable and the dry run reports exactly what a real run
would write.
"""

from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.models.enums import DispatchStatus, PoStatus
from app.money import to_cents
from scripts.history_import.workbook import (
    DispatchRow,
    DispatchSaveRow,
    OrderHeaderRow,
    OrderLineRow,
    TargetRow,
    WorkbookHistory,
)

# A workbook name that maps onto a different current DB friendly_name.
FRIDGE_NAME_ALIASES: dict[str, str] = {
    "CBC Namur": "CBC",
    "Greenhouse Collection gauche": "Greenhouse Collection Links",
    # Renamed inside Excel: ATELIER rows stop 2026-06-15, "Atelier rue du Cerf" starts 2026-06-22.
    "ATELIER": "Atelier rue du Cerf",
}

# Workbook names waiting on a business decision: their rows are reported, never imported.
UNDECIDED_FRIDGE_NAMES: dict[str, str] = {
    "CBC": "Excel 'CBC' rows until 2026-07-20: which DB fridge? (ask Mathieu)",
}

# Fridges no longer in Husky: created inactive so their history is kept.
PLACEHOLDER_FRIDGE_HUSKY_IDS: dict[str, str] = {
    "Atelier rue du Cerf": "legacy-atelier-rue-du-cerf",
    "Echantillons": "legacy-echantillons",
    "PWC Antwerpen": "legacy-pwc-antwerpen",
    "Van Mieghem Tubize": "legacy-van-mieghem-tubize",
}

ORDER_STATUS_BY_TEXT: dict[str, PoStatus] = {
    "pending": PoStatus.pending,
    "received": PoStatus.received,
    "cancelled": PoStatus.cancelled,
    "canceled": PoStatus.cancelled,
}

# A PO still "Pending" this long after its delivery date was received; Excel was never updated.
PENDING_ORDER_MAX_AGE = datetime.timedelta(days=14)

PRODUCT_CODE_WIDTH = 13
EXCEL_TIMEZONE = ZoneInfo("Europe/Brussels")


class Table(StrEnum):
    DISPATCHES = "Global Dispatch History"
    ORDER_HEADERS = "Order History (orders)"
    ORDER_LINES = "Order History (lines)"
    TARGETS = "Snacks And Drinks Target Map"


class DropReason(StrEnum):
    NON_POSITIVE_QTY = "quantity <= 0"
    BLANK_CODE_NOT_REPAIRABLE = "blank product code, name has no single code"
    UNKNOWN_PRODUCT = "product code not in catalogue"
    UNRESOLVED_FRIDGE = "fridge name not mapped"
    UNKNOWN_SUPPLIER = "supplier not in DB"
    LINE_WITHOUT_ORDER = "line has no order header"
    ORDER_WITHOUT_LINES = "order has no importable line"
    DUPLICATE_TARGET = "duplicate fridge/product target"


@dataclass(frozen=True)
class CatalogueProduct:
    id: int
    purchase_price: int
    sales_price: int
    vat_rate: Decimal


@dataclass(frozen=True)
class Catalogue:
    """The DB master data the plan resolves workbook names and codes against."""

    products_by_code: dict[str, CatalogueProduct]
    product_ids_by_name: dict[str, list[int]]
    fridge_names: set[str]
    supplier_id_by_name: dict[str, int]


@dataclass(frozen=True)
class DroppedRow:
    table: Table
    row_number: int
    reason: DropReason
    detail: str


@dataclass(frozen=True)
class RepairedCode:
    product_name: str
    product_code: str
    row_count: int


@dataclass
class PlannedDispatchLine:
    fridge_name: str
    product_id: int
    qty: int
    unit_purchase_price: int
    unit_sales_price: int
    vat_rate: Decimal


@dataclass
class PlannedDispatch:
    delivery_date: datetime.date
    status: DispatchStatus
    confirmed_at: datetime.datetime | None
    lines: list[PlannedDispatchLine]


@dataclass
class PlannedOrderLine:
    product_id: int
    qty_ordered: int
    qty_received: int
    unit_price: int
    vat_rate: Decimal


@dataclass
class PlannedOrder:
    order_no: str
    supplier_id: int
    status: PoStatus
    order_date: datetime.date
    expected_delivery_date: datetime.date
    delivery_address: str | None
    comment: str | None
    workbook_total_incl_vat: int
    lines: list[PlannedOrderLine]

    @property
    def total_ex_vat(self) -> int:
        return sum(line.qty_ordered * line.unit_price for line in self.lines)

    @property
    def total_vat(self) -> int:
        """VAT is rounded per line, the way the app's PO service totals it (R5)."""
        line_vats = [
            to_cents(Decimal(line.qty_ordered * line.unit_price) * line.vat_rate)
            for line in self.lines
        ]
        return sum(line_vats)

    @property
    def total_incl_vat(self) -> int:
        return self.total_ex_vat + self.total_vat


@dataclass(frozen=True)
class PlannedTarget:
    fridge_name: str
    product_id: int
    target_qty: int


@dataclass
class ImportPlan:
    dispatches: list[PlannedDispatch] = field(default_factory=list)
    orders: list[PlannedOrder] = field(default_factory=list)
    targets: list[PlannedTarget] = field(default_factory=list)
    dropped_rows: list[DroppedRow] = field(default_factory=list)
    repaired_codes: list[RepairedCode] = field(default_factory=list)
    unresolved_fridge_rows: Counter[str] = field(default_factory=Counter)
    unknown_supplier_orders: Counter[str] = field(default_factory=Counter)
    placeholder_fridges_used: set[str] = field(default_factory=set)
    orders_aged_to_received: list[str] = field(default_factory=list)
    orders_delivery_date_clamped: list[str] = field(default_factory=list)
    order_lines_received_clamped: int = 0
    workbook_order_numbers: list[str] = field(default_factory=list)

    def drop(self, table: Table, row_number: int, reason: DropReason, detail: str) -> None:
        dropped = DroppedRow(table=table, row_number=row_number, reason=reason, detail=detail)
        self.dropped_rows.append(dropped)

    def placeholder_fridges_to_create(self, catalogue: Catalogue) -> list[str]:
        missing = self.placeholder_fridges_used - catalogue.fridge_names
        return sorted(missing)


def build_import_plan(
    history: WorkbookHistory,
    catalogue: Catalogue,
    import_date: datetime.date,
) -> ImportPlan:
    """Map every workbook table onto planned rows, recording each dropped row and why."""
    plan = ImportPlan()
    plan.dispatches = plan_dispatches(history, catalogue, plan)
    plan.orders = plan_orders(history, catalogue, import_date, plan)
    plan.targets = plan_targets(history.targets, catalogue, plan)
    return plan


def resolve_fridge_name(workbook_name: str, catalogue: Catalogue) -> str | None:
    """Return the DB friendly_name a workbook fridge name maps to, or None if unmapped."""
    if workbook_name in UNDECIDED_FRIDGE_NAMES:
        return None
    db_name = FRIDGE_NAME_ALIASES.get(workbook_name, workbook_name)
    is_known = db_name in catalogue.fridge_names
    is_placeholder = db_name in PLACEHOLDER_FRIDGE_HUSKY_IDS
    if is_known or is_placeholder:
        return db_name
    return None


def resolve_product_code(code: str, catalogue: Catalogue) -> CatalogueProduct | None:
    """Exact code first, then the 13-digit zero-padded form Excel sometimes strips."""
    exact_match = catalogue.products_by_code.get(code)
    if exact_match is not None:
        return exact_match
    padded_code = code.zfill(PRODUCT_CODE_WIDTH)
    return catalogue.products_by_code.get(padded_code)


def plan_dispatches(
    history: WorkbookHistory,
    catalogue: Catalogue,
    plan: ImportPlan,
) -> list[PlannedDispatch]:
    """One batch per delivery date, lines summed per (fridge, product)."""
    repaired_rows = repair_blank_codes(history.dispatch_rows, catalogue, plan)
    saved_at_by_date = latest_save_by_delivery_date(history.dispatch_saves)
    rows_by_date: dict[datetime.date, list[DispatchRow]] = {}
    for row in repaired_rows:
        rows_by_date.setdefault(row.delivery_date, []).append(row)

    dispatches = []
    delivery_dates = sorted(rows_by_date)
    for delivery_date in delivery_dates:
        day_rows = rows_by_date[delivery_date]
        lines = _plan_dispatch_lines(day_rows, catalogue, plan)
        if not lines:
            continue
        status = dispatch_status_for_day(day_rows)
        confirmed_at = None
        if status is DispatchStatus.dispatched:
            confirmed_at = confirmation_time(delivery_date, saved_at_by_date)
        dispatch = PlannedDispatch(
            delivery_date=delivery_date,
            status=status,
            confirmed_at=confirmed_at,
            lines=lines,
        )
        dispatches.append(dispatch)
    return dispatches


def repair_blank_codes(
    rows: list[DispatchRow],
    catalogue: Catalogue,
    plan: ImportPlan,
) -> list[DispatchRow]:
    """Give blank-code rows the single code their product name carries in other rows.

    Blank-code rows carry 0 prices, so a repaired row takes the prices of a same-week
    row of that code, else the catalogue's. Rows whose name has zero or several codes
    are dropped.
    """
    codes_by_name: dict[str, set[str]] = {}
    same_week_rows: dict[tuple[datetime.date, str], DispatchRow] = {}
    coded_rows = [row for row in rows if row.product_code]
    for row in coded_rows:
        codes_by_name.setdefault(_name_key(row.product_name), set()).add(row.product_code)
        week_and_code = (week_start_of(row.delivery_date), row.product_code)
        same_week_rows.setdefault(week_and_code, row)

    repaired_rows = []
    repaired_counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        if row.product_code:
            repaired_rows.append(row)
            continue
        name_codes = codes_by_name.get(_name_key(row.product_name), set())
        if len(name_codes) != 1:
            plan.drop(
                table=Table.DISPATCHES,
                row_number=row.row_number,
                reason=DropReason.BLANK_CODE_NOT_REPAIRABLE,
                detail=row.product_name,
            )
            continue
        (repaired_code,) = name_codes
        same_week_row = same_week_rows.get((week_start_of(row.delivery_date), repaired_code))
        repaired_row = _reprice_with_code(row, repaired_code, same_week_row, catalogue)
        repaired_rows.append(repaired_row)
        repaired_counts[(row.product_name, repaired_code)] += 1

    for (product_name, product_code), row_count in repaired_counts.items():
        repaired = RepairedCode(
            product_name=product_name,
            product_code=product_code,
            row_count=row_count,
        )
        plan.repaired_codes.append(repaired)
    return repaired_rows


def dispatch_status_for_day(day_rows: list[DispatchRow]) -> DispatchStatus:
    """Excel flags a whole day as dispatched or not; a mixed day is a data error."""
    flags = {row.is_dispatched for row in day_rows}
    if len(flags) > 1:
        raise ValueError(f"Mixed 'Is Dispatched?' values on {day_rows[0].delivery_date}")
    if True in flags:
        return DispatchStatus.dispatched
    return DispatchStatus.saved


def latest_save_by_delivery_date(
    saves: list[DispatchSaveRow],
) -> dict[datetime.date, datetime.datetime]:
    latest: dict[datetime.date, datetime.datetime] = {}
    for save in saves:
        current = latest.get(save.delivery_date)
        if current is None or save.last_saved_local > current:
            latest[save.delivery_date] = save.last_saved_local
    return latest


def confirmation_time(
    delivery_date: datetime.date,
    saved_at_by_date: dict[datetime.date, datetime.datetime],
) -> datetime.datetime:
    """Excel's naive Brussels 'Last Saved Time' as UTC; midnight Brussels when absent."""
    midnight = datetime.datetime.combine(delivery_date, datetime.time())
    local_time = saved_at_by_date.get(delivery_date, midnight)
    return local_time.replace(tzinfo=EXCEL_TIMEZONE).astimezone(datetime.UTC)


def plan_orders(
    history: WorkbookHistory,
    catalogue: Catalogue,
    import_date: datetime.date,
    plan: ImportPlan,
) -> list[PlannedOrder]:
    headers_by_order_no = _index_order_headers(history.order_headers)
    plan.workbook_order_numbers = sorted(headers_by_order_no)
    lines_by_order_no = _plan_order_lines(history.order_lines, headers_by_order_no, catalogue, plan)

    orders = []
    for order_no, header in headers_by_order_no.items():
        supplier_id = catalogue.supplier_id_by_name.get(header.supplier_name)
        if supplier_id is None:
            plan.unknown_supplier_orders[header.supplier_name] += 1
            plan.drop(
                table=Table.ORDER_HEADERS,
                row_number=header.row_number,
                reason=DropReason.UNKNOWN_SUPPLIER,
                detail=order_no,
            )
            continue
        lines = lines_by_order_no.get(order_no, [])
        if not lines:
            plan.drop(
                table=Table.ORDER_HEADERS,
                row_number=header.row_number,
                reason=DropReason.ORDER_WITHOUT_LINES,
                detail=order_no,
            )
            continue
        expected_delivery_date = _expected_delivery_date(header, plan)
        order = PlannedOrder(
            order_no=order_no,
            supplier_id=supplier_id,
            status=order_status(header, expected_delivery_date, import_date, plan),
            order_date=header.order_date,
            expected_delivery_date=expected_delivery_date,
            delivery_address=header.delivery_address,
            comment=header.comment,
            workbook_total_incl_vat=header.workbook_total_incl_vat,
            lines=lines,
        )
        orders.append(order)
    return orders


def order_status(
    header: OrderHeaderRow,
    expected_delivery_date: datetime.date,
    import_date: datetime.date,
    plan: ImportPlan,
) -> PoStatus:
    """Workbook status, except long-overdue 'Pending' orders count as received."""
    status = ORDER_STATUS_BY_TEXT.get(header.status_text.lower())
    if status is None:
        raise ValueError(f"Order {header.order_no}: unknown status {header.status_text!r}")
    oldest_open_delivery_date = import_date - PENDING_ORDER_MAX_AGE
    is_overdue = expected_delivery_date < oldest_open_delivery_date
    if status is PoStatus.pending and is_overdue:
        plan.orders_aged_to_received.append(header.order_no)
        return PoStatus.received
    return status


def plan_targets(
    rows: list[TargetRow],
    catalogue: Catalogue,
    plan: ImportPlan,
) -> list[PlannedTarget]:
    targets_by_key: dict[tuple[str, int], PlannedTarget] = {}
    for row in rows:
        fridge_name = _resolve_row_fridge(
            workbook_name=row.fridge_name,
            table=Table.TARGETS,
            row_number=row.row_number,
            catalogue=catalogue,
            plan=plan,
        )
        if fridge_name is None:
            continue
        product = resolve_product_code(row.product_code, catalogue)
        if product is None:
            plan.drop(
                table=Table.TARGETS,
                row_number=row.row_number,
                reason=DropReason.UNKNOWN_PRODUCT,
                detail=row.product_code,
            )
            continue
        target_key = (fridge_name, product.id)
        if target_key in targets_by_key:
            plan.drop(
                table=Table.TARGETS,
                row_number=row.row_number,
                reason=DropReason.DUPLICATE_TARGET,
                detail=row.product_code,
            )
            continue
        targets_by_key[target_key] = PlannedTarget(
            fridge_name=fridge_name,
            product_id=product.id,
            target_qty=row.target_qty,
        )
    return list(targets_by_key.values())


def highest_order_sequence_by_year(order_numbers: list[str]) -> dict[int, int]:
    """'2026-00531' -> {2026: 531}, keeping the highest sequence per year."""
    highest: dict[int, int] = {}
    for order_no in order_numbers:
        year_text, sequence_text = order_no.split("-")
        year = int(year_text)
        sequence = int(sequence_text)
        highest[year] = max(highest.get(year, 0), sequence)
    return highest


def week_start_of(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def _plan_dispatch_lines(
    day_rows: list[DispatchRow],
    catalogue: Catalogue,
    plan: ImportPlan,
) -> list[PlannedDispatchLine]:
    lines_by_key: dict[tuple[str, int], PlannedDispatchLine] = {}
    for row in day_rows:
        if row.quantity <= 0:
            plan.drop(
                table=Table.DISPATCHES,
                row_number=row.row_number,
                reason=DropReason.NON_POSITIVE_QTY,
                detail=str(row.quantity),
            )
            continue
        fridge_name = _resolve_row_fridge(
            workbook_name=row.fridge_name,
            table=Table.DISPATCHES,
            row_number=row.row_number,
            catalogue=catalogue,
            plan=plan,
        )
        if fridge_name is None:
            continue
        product = resolve_product_code(row.product_code, catalogue)
        if product is None:
            plan.drop(
                table=Table.DISPATCHES,
                row_number=row.row_number,
                reason=DropReason.UNKNOWN_PRODUCT,
                detail=row.product_code,
            )
            continue
        line_key = (fridge_name, product.id)
        existing_line = lines_by_key.get(line_key)
        if existing_line is not None:
            existing_line.qty += row.quantity
            continue
        lines_by_key[line_key] = _dispatch_line(row, fridge_name, product)
    return list(lines_by_key.values())


def _dispatch_line(
    row: DispatchRow,
    fridge_name: str,
    product: CatalogueProduct,
) -> PlannedDispatchLine:
    return PlannedDispatchLine(
        fridge_name=fridge_name,
        product_id=product.id,
        qty=row.quantity,
        unit_purchase_price=row.purchase_price,
        unit_sales_price=row.sales_price,
        vat_rate=row.vat_rate,
    )


def _plan_order_lines(
    rows: list[OrderLineRow],
    headers_by_order_no: dict[str, OrderHeaderRow],
    catalogue: Catalogue,
    plan: ImportPlan,
) -> dict[str, list[PlannedOrderLine]]:
    """Valid lines per order, duplicate (order, product) lines summed."""
    lines_by_order: dict[str, dict[int, PlannedOrderLine]] = {}
    for row in rows:
        if row.order_no not in headers_by_order_no:
            plan.drop(
                table=Table.ORDER_LINES,
                row_number=row.row_number,
                reason=DropReason.LINE_WITHOUT_ORDER,
                detail=row.order_no,
            )
            continue
        if row.qty_ordered <= 0:
            plan.drop(
                table=Table.ORDER_LINES,
                row_number=row.row_number,
                reason=DropReason.NON_POSITIVE_QTY,
                detail=row.order_no,
            )
            continue
        product_id = _resolve_order_line_product(row, catalogue)
        if product_id is None:
            detail = f"{row.order_no} {row.product_code or row.product_name}"
            plan.drop(
                table=Table.ORDER_LINES,
                row_number=row.row_number,
                reason=DropReason.UNKNOWN_PRODUCT,
                detail=detail,
            )
            continue
        order_lines = lines_by_order.setdefault(row.order_no, {})
        existing_line = order_lines.get(product_id)
        if existing_line is not None:
            existing_line.qty_ordered += row.qty_ordered
            existing_line.qty_received += row.qty_received
            continue
        order_lines[product_id] = PlannedOrderLine(
            product_id=product_id,
            qty_ordered=row.qty_ordered,
            qty_received=row.qty_received,
            unit_price=row.unit_price,
            vat_rate=row.vat_rate,
        )

    planned_lines_by_order = {}
    for order_no, lines_by_product in lines_by_order.items():
        planned_lines = list(lines_by_product.values())
        _clamp_negative_received(planned_lines, plan)
        planned_lines_by_order[order_no] = planned_lines
    return planned_lines_by_order


def _clamp_negative_received(lines: list[PlannedOrderLine], plan: ImportPlan) -> None:
    """A negative 'received' is a legacy typo, and the DB requires qty_received >= 0."""
    for line in lines:
        if line.qty_received < 0:
            line.qty_received = 0
            plan.order_lines_received_clamped += 1


def _resolve_order_line_product(row: OrderLineRow, catalogue: Catalogue) -> int | None:
    """By code; a blank code falls back to a product name that matches exactly one product."""
    if row.product_code:
        product = resolve_product_code(row.product_code, catalogue)
        if product is None:
            return None
        return product.id
    name_matches = catalogue.product_ids_by_name.get(_name_key(row.product_name), [])
    if len(name_matches) != 1:
        return None
    return name_matches[0]


def _index_order_headers(headers: list[OrderHeaderRow]) -> dict[str, OrderHeaderRow]:
    headers_by_order_no: dict[str, OrderHeaderRow] = {}
    for header in headers:
        if header.order_no in headers_by_order_no:
            raise ValueError(f"Order {header.order_no} appears twice in the order headers")
        headers_by_order_no[header.order_no] = header
    return headers_by_order_no


def _expected_delivery_date(header: OrderHeaderRow, plan: ImportPlan) -> datetime.date:
    """A missing date defaults to the order date; an earlier one is raised to it (DB CHECK)."""
    expected = header.expected_delivery_date or header.order_date
    if expected < header.order_date:
        plan.orders_delivery_date_clamped.append(header.order_no)
        return header.order_date
    return expected


def _resolve_row_fridge(
    workbook_name: str,
    table: Table,
    row_number: int,
    catalogue: Catalogue,
    plan: ImportPlan,
) -> str | None:
    fridge_name = resolve_fridge_name(workbook_name, catalogue)
    if fridge_name is None:
        plan.unresolved_fridge_rows[workbook_name] += 1
        plan.drop(table, row_number, DropReason.UNRESOLVED_FRIDGE, workbook_name)
        return None
    if fridge_name in PLACEHOLDER_FRIDGE_HUSKY_IDS:
        plan.placeholder_fridges_used.add(fridge_name)
    return fridge_name


def _reprice_with_code(
    row: DispatchRow,
    product_code: str,
    same_week_row: DispatchRow | None,
    catalogue: Catalogue,
) -> DispatchRow:
    if same_week_row is not None:
        return replace(
            row,
            product_code=product_code,
            purchase_price=same_week_row.purchase_price,
            sales_price=same_week_row.sales_price,
            vat_rate=same_week_row.vat_rate,
        )
    product = resolve_product_code(product_code, catalogue)
    if product is None:
        return replace(row, product_code=product_code)
    return replace(
        row,
        product_code=product_code,
        purchase_price=product.purchase_price,
        sales_price=product.sales_price,
        vat_rate=product.vat_rate,
    )


def _name_key(product_name: str) -> str:
    return product_name.strip().lower()
