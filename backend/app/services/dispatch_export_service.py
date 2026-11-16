"""Dispatch Excel export, laid out for printing.

Sheets, in order:
* "Summary": one row per fridge (client, products, units) with a total; no prices.
* One pick list per fridge, ordered by client then fridge: title (fridge, client,
  delivery date), product rows grouped by category in driver print order, bold
  quantities, a "Packed" tick column and the fridge total. A4 portrait, fit to
  width, header row repeated on every page, gridlines printed, no prices.
* "Dispatch lines" and "Fridge x Product": the office data sheets (with prices).

One sheet per fridge (not one per client with page breaks) because a packer fills
one fridge's crates at a time: each sheet prints on its own page(s) with its own
total, the sheet tabs work as an index, and a single fridge can be reprinted alone.

Prices are the ones snapshot when the day was dispatched; before that the current
catalogue prices (per-fridge sales override first) stand in.
"""

from __future__ import annotations

import datetime
import io
import re

import polars as pl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.operations import Dispatch
from app.schemas.masters import api_error
from app.services.report_export_service import ExcelDocument

SUMMARY_SHEET = "Summary"
LINES_SHEET = "Dispatch lines"
GRID_SHEET = "Fridge x Product"
NO_CLIENT = "No client"
UNNAMED_SHEET = "Fridge"
# Excel sheet names: at most 31 characters, none of []:*?/\ and unique ignoring case.
SHEET_NAME_MAX_LENGTH = 31
FORBIDDEN_SHEET_NAME_CHARACTERS = re.compile(r"[\[\]:*?/\\]")
EURO_FORMAT = "#,##0.00"
CENTS_PER_EURO = 100

FRIDGE = "Fridge"
CLIENT = "Client"
QTY = "Qty"
PRODUCT_CODE = "Product code"
PRODUCT = "Product"
PRODUCTS = "Products"
UNITS = "Units"
PACKED = "Packed"
TOTAL = "Total"
UNIT_PURCHASE_PRICE = "Unit purchase price (EUR)"
UNIT_SALES_PRICE = "Unit sales price (EUR)"
LINE_COST = "Line cost (EUR)"

PICK_LIST_HEADER = [PRODUCT_CODE, PRODUCT, QTY, PACKED]
PICK_LIST_COLUMN_WIDTHS = {"A": 16, "B": 50, "C": 8, "D": 9}
SUMMARY_HEADER = [CLIENT, FRIDGE, PRODUCTS, UNITS]
SUMMARY_COLUMN_WIDTHS = {"A": 28, "B": 34, "C": 10, "D": 10}
# Title block: fridge (or day) name, client, delivery date, blank spacer, then the header.
TABLE_HEADER_ROW = 5
QTY_COLUMN = 3
DATA_SHEET_COLUMN_WIDTH = 18

TITLE_FONT = Font(bold=True, size=16)
SUBTITLE_FONT = Font(size=12)
HEADER_FONT = Font(bold=True)
CATEGORY_FONT = Font(bold=True, italic=True)
QTY_FONT = Font(bold=True, size=12)
TOTAL_FONT = Font(bold=True, size=12)
HEADER_FILL = PatternFill(fill_type="solid", start_color="D9D9D9")
CATEGORY_FILL = PatternFill(fill_type="solid", start_color="F2F2F2")
CENTERED = Alignment(horizontal="center")
# The sheet name (&A) and page numbers on every printed page, so loose pages can be sorted.
PRINT_FOOTER = "&A - page &P of &N"

EXPORT_LINES_SQL = text(
    """
    SELECT
        f.friendly_name AS fridge,
        COALESCE(cl.name, :no_client) AS client,
        c.name AS category,
        c.dispatch_print_order AS category_print_order,
        s.name AS supplier,
        p.code AS product_code,
        p.name AS product_name,
        dl.qty AS qty,
        COALESCE(dl.unit_purchase_price, p.purchase_price) AS unit_purchase_cents,
        COALESCE(dl.unit_sales_price, fpp.sales_price, p.sales_price) AS unit_sales_cents,
        COALESCE(dl.vat_rate, p.vat_rate)::float8 AS vat_rate
    FROM dispatch_lines dl
    JOIN fridges f ON f.id = dl.fridge_id
    LEFT JOIN clients cl ON cl.id = f.client_id
    JOIN products p ON p.id = dl.product_id
    JOIN categories c ON c.id = p.category_id
    LEFT JOIN suppliers s ON s.id = p.supplier_id
    LEFT JOIN fridge_product_prices fpp
        ON fpp.fridge_id = dl.fridge_id
       AND fpp.product_id = dl.product_id
    WHERE dl.dispatch_id = :dispatch_id
      AND dl.delivery_date = :delivery_date
    """
)

EXPORT_LINES_SCHEMA = {
    "fridge": pl.Utf8,
    "client": pl.Utf8,
    "category": pl.Utf8,
    "category_print_order": pl.Int64,
    "supplier": pl.Utf8,
    "product_code": pl.Utf8,
    "product_name": pl.Utf8,
    "qty": pl.Int64,
    "unit_purchase_cents": pl.Int64,
    "unit_sales_cents": pl.Int64,
    "vat_rate": pl.Float64,
}
PRINT_ORDER = ["client", "fridge", "category_print_order", "product_name"]


def build_dispatch_xlsx(dispatch: Dispatch, session: Session) -> ExcelDocument:
    """Render the dispatch day as a printable ``.xlsx`` (see the module docstring)."""
    lines = _load_export_lines(dispatch, session)
    if lines.is_empty():
        raise api_error(
            409,
            "conflict",
            "This dispatch has no lines to export",
            {"dispatch_id": dispatch.id},
        )
    content = render_dispatch_workbook(lines, dispatch.delivery_date)
    filename = f"dispatch_{dispatch.delivery_date.isoformat()}.xlsx"
    return ExcelDocument(filename=filename, content=content)


def render_dispatch_workbook(lines: pl.DataFrame, delivery_date: datetime.date) -> bytes:
    """The workbook bytes for export ``lines`` (``EXPORT_LINES_SCHEMA``) of one delivery day."""
    sorted_lines = lines.sort(PRINT_ORDER)
    lines_per_fridge = sorted_lines.partition_by("fridge", maintain_order=True)
    fridge_names = [fridge_lines["fridge"][0] for fridge_lines in lines_per_fridge]
    fridge_sheet_names = _unique_sheet_names(
        fridge_names,
        taken=[SUMMARY_SHEET, LINES_SHEET, GRID_SHEET],
    )

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = SUMMARY_SHEET
    _write_summary_sheet(summary_sheet, lines_per_fridge, delivery_date)
    for fridge_lines, sheet_name in zip(lines_per_fridge, fridge_sheet_names):
        fridge_sheet = workbook.create_sheet(sheet_name)
        _write_pick_list_sheet(fridge_sheet, fridge_lines, delivery_date)
    _write_data_sheet(
        workbook.create_sheet(LINES_SHEET),
        _build_line_sheet(sorted_lines),
        euro_columns=[UNIT_PURCHASE_PRICE, UNIT_SALES_PRICE, LINE_COST],
    )
    _write_data_sheet(
        workbook.create_sheet(GRID_SHEET),
        _build_fridge_product_grid(sorted_lines),
        euro_columns=[],
    )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _load_export_lines(dispatch: Dispatch, session: Session) -> pl.DataFrame:
    rows = session.execute(
        EXPORT_LINES_SQL,
        {
            "dispatch_id": dispatch.id,
            "delivery_date": dispatch.delivery_date,
            "no_client": NO_CLIENT,
        },
    ).mappings()
    line_records = [dict(row) for row in rows]
    return pl.DataFrame(line_records, schema=EXPORT_LINES_SCHEMA)


def _write_summary_sheet(
    sheet: Worksheet,
    lines_per_fridge: list[pl.DataFrame],
    delivery_date: datetime.date,
) -> None:
    _write_title_block(
        sheet,
        title=f"Dispatch {_format_delivery_date(delivery_date)}",
        subtitles=[f"{len(lines_per_fridge)} fridges"],
    )
    _write_header_row(sheet, SUMMARY_HEADER)
    for fridge_lines in lines_per_fridge:
        sheet.append(
            [
                fridge_lines["client"][0],
                fridge_lines["fridge"][0],
                fridge_lines.height,
                fridge_lines["qty"].sum(),
            ]
        )
    all_product_lines = sum(fridge_lines.height for fridge_lines in lines_per_fridge)
    all_units = sum(fridge_lines["qty"].sum() for fridge_lines in lines_per_fridge)
    sheet.append([TOTAL, None, all_product_lines, all_units])
    _style_total_row(sheet)
    _set_column_widths(sheet, SUMMARY_COLUMN_WIDTHS)
    _apply_print_setup(sheet)


def _write_pick_list_sheet(
    sheet: Worksheet,
    fridge_lines: pl.DataFrame,
    delivery_date: datetime.date,
) -> None:
    _write_title_block(
        sheet,
        title=fridge_lines["fridge"][0],
        subtitles=[
            f"Client: {fridge_lines['client'][0]}",
            f"Delivery: {_format_delivery_date(delivery_date)}",
        ],
    )
    _write_header_row(sheet, PICK_LIST_HEADER)
    lines_per_category = fridge_lines.partition_by("category", maintain_order=True)
    for category_lines in lines_per_category:
        _write_category_row(sheet, category_lines)
        product_rows = category_lines.select("product_code", "product_name", "qty").rows()
        for product_code, product_name, qty in product_rows:
            sheet.append([product_code, product_name, qty, None])
            qty_cell = sheet.cell(row=sheet.max_row, column=QTY_COLUMN)
            qty_cell.font = QTY_FONT
            qty_cell.alignment = CENTERED
    sheet.append([TOTAL, f"{fridge_lines.height} products", fridge_lines["qty"].sum(), None])
    _style_total_row(sheet)
    sheet.cell(row=sheet.max_row, column=QTY_COLUMN).alignment = CENTERED
    _set_column_widths(sheet, PICK_LIST_COLUMN_WIDTHS)
    _apply_print_setup(sheet)


def _write_title_block(sheet: Worksheet, title: str, subtitles: list[str]) -> None:
    sheet.append([title])
    sheet["A1"].font = TITLE_FONT
    for subtitle in subtitles:
        sheet.append([subtitle])
        sheet.cell(row=sheet.max_row, column=1).font = SUBTITLE_FONT


def _write_header_row(sheet: Worksheet, header: list[str]) -> None:
    """Header at the fixed ``TABLE_HEADER_ROW``; later ``append`` calls continue below it."""
    for column, label in enumerate(header, start=1):
        header_cell = sheet.cell(row=TABLE_HEADER_ROW, column=column, value=label)
        header_cell.font = HEADER_FONT
        header_cell.fill = HEADER_FILL
    sheet.cell(row=TABLE_HEADER_ROW, column=QTY_COLUMN).alignment = CENTERED
    sheet.freeze_panes = f"A{TABLE_HEADER_ROW + 1}"


def _write_category_row(sheet: Worksheet, category_lines: pl.DataFrame) -> None:
    category_label = f"{category_lines['category'][0]} ({category_lines['qty'].sum()} units)"
    sheet.append([category_label])
    category_row = sheet.max_row
    for column in range(1, len(PICK_LIST_HEADER) + 1):
        category_cell = sheet.cell(row=category_row, column=column)
        category_cell.font = CATEGORY_FONT
        category_cell.fill = CATEGORY_FILL


def _style_total_row(sheet: Worksheet) -> None:
    total_row = sheet.max_row
    for column in range(1, sheet.max_column + 1):
        sheet.cell(row=total_row, column=column).font = TOTAL_FONT


def _set_column_widths(sheet: Worksheet, widths: dict[str, int]) -> None:
    for column_letter, width in widths.items():
        sheet.column_dimensions[column_letter].width = width


def _apply_print_setup(sheet: Worksheet) -> None:
    """A4 portrait, one page wide (as many pages tall as needed), header row on every page."""
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.orientation = sheet.ORIENTATION_PORTRAIT
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_options.gridLines = True
    sheet.print_options.horizontalCentered = True
    sheet.print_title_rows = f"{TABLE_HEADER_ROW}:{TABLE_HEADER_ROW}"
    sheet.oddFooter.center.text = PRINT_FOOTER


def _write_data_sheet(
    sheet: Worksheet,
    table: pl.DataFrame,
    euro_columns: list[str],
) -> None:
    sheet.append(table.columns)
    for header_cell in sheet[1]:
        header_cell.font = HEADER_FONT
    for row in table.rows():
        sheet.append(row)
    for column_index, column_name in enumerate(table.columns, start=1):
        column_letter = sheet.cell(row=1, column=column_index).column_letter
        sheet.column_dimensions[column_letter].width = DATA_SHEET_COLUMN_WIDTH
        if column_name not in euro_columns:
            continue
        for row_index in range(2, sheet.max_row + 1):
            sheet.cell(row=row_index, column=column_index).number_format = EURO_FORMAT
    sheet.freeze_panes = "A2"


def _build_line_sheet(lines: pl.DataFrame) -> pl.DataFrame:
    return lines.select(
        pl.col("fridge").alias(FRIDGE),
        pl.col("client").alias(CLIENT),
        pl.col("category").alias("Category"),
        pl.col("supplier").alias("Supplier"),
        pl.col("product_code").alias(PRODUCT_CODE),
        pl.col("product_name").alias(PRODUCT),
        pl.col("qty").alias(QTY),
        (pl.col("unit_purchase_cents") / CENTS_PER_EURO).alias(UNIT_PURCHASE_PRICE),
        (pl.col("unit_sales_cents") / CENTS_PER_EURO).alias(UNIT_SALES_PRICE),
        pl.col("vat_rate").alias("VAT rate"),
        (pl.col("qty") * pl.col("unit_purchase_cents") / CENTS_PER_EURO).alias(LINE_COST),
    )


def _build_fridge_product_grid(lines: pl.DataFrame) -> pl.DataFrame:
    """One row per fridge, one column per product in driver-sheet category order.

    The product code in each header keeps two products with the same name apart.
    """
    labelled_lines = lines.with_columns(
        pl.format("{} ({})", pl.col("product_name"), pl.col("product_code")).alias("product_label")
    )
    product_labels = (
        labelled_lines.sort("category_print_order", "product_name")["product_label"]
        .unique(maintain_order=True)
        .to_list()
    )
    return (
        labelled_lines.pivot(
            on="product_label",
            index="fridge",
            values="qty",
        )
        .rename({"fridge": FRIDGE})
        .select(FRIDGE, *product_labels)
    )


def _format_delivery_date(delivery_date: datetime.date) -> str:
    return f"{delivery_date:%A} {delivery_date.day} {delivery_date:%B %Y}"


def _unique_sheet_names(names: list[str], taken: list[str]) -> list[str]:
    """Valid Excel sheet names for ``names``, numbered when two would clash."""
    used_names = {name.lower() for name in taken}
    sheet_names: list[str] = []
    for name in names:
        # Excel also refuses a sheet name that starts or ends with an apostrophe.
        cleaned_name = (
            FORBIDDEN_SHEET_NAME_CHARACTERS.sub(" ", name).strip(" '") or UNNAMED_SHEET
        )
        base_name = cleaned_name[:SHEET_NAME_MAX_LENGTH]
        sheet_name = base_name
        copy_number = 2
        while sheet_name.lower() in used_names:
            suffix = f" ({copy_number})"
            sheet_name = base_name[: SHEET_NAME_MAX_LENGTH - len(suffix)] + suffix
            copy_number += 1
        used_names.add(sheet_name.lower())
        sheet_names.append(sheet_name)
    return sheet_names
