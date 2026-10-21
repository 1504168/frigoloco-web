"""Read the Forecasting workbook's history tables into typed rows.

Tables are located by their Excel table name, so a table that grows week by week
never needs a new cell range. Cell values are converted once here (codes to text,
euros to cents, flags to bool); anything malformed fails loudly with its row.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from app.money import euros_to_cents

DISPATCH_TABLE = "GlobalDispatchHistoryTable"
DISPATCH_SAVES_TABLE = "GlobalDispatchHistorySummaryTable"
ORDER_HEADERS_TABLE = "OrdersSummaryTable"
ORDER_LINES_TABLE = "OrdersLineItemsTable"
TARGETS_TABLE = "Snacks_And_Drinks_Target_MapTable"

DAY_OFFSETS: dict[str, int] = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}

DAY_NAME_TYPOS: dict[str, str] = {
    "Wednesay": "Wednesday",
}

VAT_DECIMAL_PLACES = Decimal("0.0001")
# Codes pasted from other tools sometimes keep a leading tab ("\t0000073729082").
CODE_PADDING_CHARACTERS = " \t"


@dataclass(frozen=True)
class DispatchRow:
    row_number: int
    delivery_date: datetime.date
    fridge_name: str
    product_code: str
    product_name: str
    quantity: int
    purchase_price: int
    sales_price: int
    vat_rate: Decimal
    is_dispatched: bool


@dataclass(frozen=True)
class DispatchSaveRow:
    delivery_date: datetime.date
    last_saved_local: datetime.datetime


@dataclass(frozen=True)
class OrderHeaderRow:
    row_number: int
    order_no: str
    supplier_name: str
    comment: str | None
    order_date: datetime.date
    expected_delivery_date: datetime.date | None
    delivery_address: str | None
    workbook_total_incl_vat: int
    status_text: str


@dataclass(frozen=True)
class OrderLineRow:
    row_number: int
    order_no: str
    product_code: str
    product_name: str
    unit_price: int
    vat_rate: Decimal
    qty_ordered: int
    qty_received: int


@dataclass(frozen=True)
class TargetRow:
    row_number: int
    fridge_name: str
    product_code: str
    product_name: str
    target_qty: int


@dataclass(frozen=True)
class WorkbookHistory:
    dispatch_rows: list[DispatchRow]
    dispatch_saves: list[DispatchSaveRow]
    order_headers: list[OrderHeaderRow]
    order_lines: list[OrderLineRow]
    targets: list[TargetRow]


@dataclass(frozen=True)
class TableRow:
    """One non-empty table row: its sheet row number and values keyed by header."""

    row_number: int
    values: dict[str, object]


def read_workbook_history(workbook_path: Path) -> WorkbookHistory:
    """Read every history table the importer needs from the workbook."""
    workbook = openpyxl.load_workbook(workbook_path, read_only=False, data_only=True)
    dispatch_table = read_table(workbook, DISPATCH_TABLE)
    saves_table = read_table(workbook, DISPATCH_SAVES_TABLE)
    headers_table = read_table(workbook, ORDER_HEADERS_TABLE)
    lines_table = read_table(workbook, ORDER_LINES_TABLE)
    targets_table = read_table(workbook, TARGETS_TABLE)
    return WorkbookHistory(
        dispatch_rows=[parse_dispatch_row(row) for row in dispatch_table],
        dispatch_saves=parse_dispatch_saves(saves_table),
        order_headers=[parse_order_header(row) for row in headers_table],
        order_lines=[parse_order_line(row) for row in lines_table],
        targets=[parse_target_row(row) for row in targets_table],
    )


def read_table(workbook: openpyxl.Workbook, table_name: str) -> list[TableRow]:
    """Return a table's non-empty data rows, located by Excel table name."""
    for worksheet in workbook.worksheets:
        if table_name in worksheet.tables:
            return _table_rows(worksheet, worksheet.tables[table_name].ref)
    raise KeyError(f"Table {table_name!r} not found in workbook")


def parse_dispatch_row(row: TableRow) -> DispatchRow:
    values = row.values
    return DispatchRow(
        row_number=row.row_number,
        delivery_date=compute_delivery_date(values["Week Start Date"], values["Dispatch Day"]),
        fridge_name=clean_text(values["Fridge Name"]),
        product_code=clean_code(values["Product Code"]),
        product_name=clean_text(values["Product Name"]),
        quantity=whole_number(values["Quantity"]),
        purchase_price=euros_to_cents(values["Purchase Price"] or 0),
        sales_price=euros_to_cents(values["Sales Price"] or 0),
        vat_rate=vat_fraction(values["Vat (%)"]),
        is_dispatched=excel_flag(values["Is Dispatched?"]),
    )


def parse_dispatch_saves(rows: list[TableRow]) -> list[DispatchSaveRow]:
    """Save stamps are optional metadata: rows without a date or a day name are skipped."""
    saves = []
    for row in rows:
        week_start = row.values["Week Start Date"]
        last_saved = row.values["Last Saved Time"]
        day_name = correct_day_name(row.values["Dispatch Day"])
        has_dates = isinstance(week_start, datetime.datetime) and isinstance(
            last_saved, datetime.datetime
        )
        if has_dates and day_name in DAY_OFFSETS:
            delivery_date = compute_delivery_date(week_start, day_name)
            saves.append(DispatchSaveRow(delivery_date=delivery_date, last_saved_local=last_saved))
    return saves


def parse_order_header(row: TableRow) -> OrderHeaderRow:
    values = row.values
    expected_delivery = values["Expected Delivery Date"]
    return OrderHeaderRow(
        row_number=row.row_number,
        order_no=clean_text(values["Order ID"]),
        supplier_name=clean_text(values["Supplier Name"]),
        comment=optional_text(values["Comment"]),
        order_date=values["Order Date"].date(),
        expected_delivery_date=expected_delivery.date() if expected_delivery else None,
        delivery_address=optional_text(values["Delivery Address"]),
        workbook_total_incl_vat=euros_to_cents(values["Total Amount(Incl. Vat)"] or 0),
        status_text=clean_text(values["Order Status"]),
    )


def parse_order_line(row: TableRow) -> OrderLineRow:
    values = row.values
    return OrderLineRow(
        row_number=row.row_number,
        order_no=clean_text(values["Order ID"]),
        product_code=clean_code(values["Product ID"]),
        product_name=clean_text(values["Product Name"]),
        unit_price=euros_to_cents(values["Purchase Price"] or 0),
        vat_rate=vat_fraction(values["Vat"]),
        qty_ordered=whole_number(values["# Items To Be Ordered"]),
        qty_received=whole_number(values["# Items Received"]),
    )


def parse_target_row(row: TableRow) -> TargetRow:
    values = row.values
    return TargetRow(
        row_number=row.row_number,
        fridge_name=clean_text(values["Client Name"]),
        product_code=clean_code(values["Product Code"]),
        product_name=clean_text(values["Product Name"]),
        target_qty=whole_number(values["Target Amount"]),
    )


def compute_delivery_date(week_start: object, day_name: object) -> datetime.date:
    """Delivery date = the row's Monday week start plus the dispatch day's offset."""
    day_offset = DAY_OFFSETS[correct_day_name(day_name)]
    return week_start.date() + datetime.timedelta(days=day_offset)


def correct_day_name(value: object) -> str:
    typed_day_name = clean_text(value)
    return DAY_NAME_TYPOS.get(typed_day_name, typed_day_name)


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def optional_text(value: object) -> str | None:
    text_value = clean_text(value)
    return text_value or None


def clean_code(value: object) -> str:
    """Product codes are TEXT; Excel may hand back a number for short codes (2157)."""
    if isinstance(value, (int, float)):
        return str(whole_number(value))
    if value is None:
        return ""
    return str(value).strip(CODE_PADDING_CHARACTERS)


def whole_number(value: object) -> int:
    """A blank quantity cell is 0; a fractional quantity is a data error."""
    if value is None:
        return 0
    number = Decimal(str(value))
    if number != number.to_integral_value():
        raise ValueError(f"Expected a whole number, got {value!r}")
    return int(number)


def vat_fraction(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(VAT_DECIMAL_PLACES)


def excel_flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"Expected TRUE/FALSE, got {value!r}")
    return value


def _table_rows(worksheet: Worksheet, cell_range: str) -> list[TableRow]:
    cells = worksheet[cell_range]
    header_cells = cells[0]
    headers = [cell.value for cell in header_cells]
    data_rows = cells[1:]
    rows = []
    for row_cells in data_rows:
        values = dict(zip(headers, [cell.value for cell in row_cells]))
        is_empty = all(value in (None, "") for value in values.values())
        if not is_empty:
            rows.append(TableRow(row_number=row_cells[0].row, values=values))
    return rows
