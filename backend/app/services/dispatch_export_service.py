"""Dispatch Excel export: one row per fridge x product line, plus a fridge x product grid.

Prices are the ones snapshot when the day was dispatched; before that the current
catalogue prices (per-fridge sales override first) stand in.
"""

from __future__ import annotations

import io

import polars as pl
import xlsxwriter
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.operations import Dispatch
from app.schemas.masters import api_error
from app.services.report_export_service import ExcelDocument

LINES_SHEET = "Dispatch lines"
GRID_SHEET = "Fridge x Product"
EURO_FORMAT = "#,##0.00"
CENTS_PER_EURO = 100

FRIDGE = "Fridge"
QTY = "Qty"
PRODUCT_CODE = "Product code"
PRODUCT = "Product"
UNIT_PURCHASE_PRICE = "Unit purchase price (EUR)"
UNIT_SALES_PRICE = "Unit sales price (EUR)"
LINE_COST = "Line cost (EUR)"

EXPORT_LINES_SQL = text(
    """
    SELECT
        f.friendly_name AS fridge,
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
    JOIN products p ON p.id = dl.product_id
    JOIN categories c ON c.id = p.category_id
    LEFT JOIN suppliers s ON s.id = p.supplier_id
    LEFT JOIN fridge_product_prices fpp
        ON fpp.fridge_id = dl.fridge_id
       AND fpp.product_id = dl.product_id
    WHERE dl.dispatch_id = :dispatch_id
      AND dl.delivery_date = :delivery_date
    ORDER BY f.friendly_name, c.dispatch_print_order, p.name
    """
)

EXPORT_LINES_SCHEMA = {
    "fridge": pl.Utf8,
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


def build_dispatch_xlsx(dispatch: Dispatch, session: Session) -> ExcelDocument:
    """Render the dispatch day as an ``.xlsx`` with a line sheet and a quantity grid."""
    lines = _load_export_lines(dispatch, session)
    if lines.is_empty():
        raise api_error(
            409,
            "conflict",
            "This dispatch has no lines to export",
            {"dispatch_id": dispatch.id},
        )
    line_sheet = _build_line_sheet(lines)
    grid_sheet = _build_fridge_product_grid(lines)

    buffer = io.BytesIO()
    with xlsxwriter.Workbook(buffer) as workbook:
        line_sheet.write_excel(
            workbook=workbook,
            worksheet=LINES_SHEET,
            autofit=True,
            column_formats={
                UNIT_PURCHASE_PRICE: EURO_FORMAT,
                UNIT_SALES_PRICE: EURO_FORMAT,
                LINE_COST: EURO_FORMAT,
            },
        )
        grid_sheet.write_excel(workbook=workbook, worksheet=GRID_SHEET, autofit=True)

    filename = f"dispatch_{dispatch.delivery_date.isoformat()}.xlsx"
    return ExcelDocument(filename=filename, content=buffer.getvalue())


def _load_export_lines(dispatch: Dispatch, session: Session) -> pl.DataFrame:
    rows = session.execute(
        EXPORT_LINES_SQL,
        {"dispatch_id": dispatch.id, "delivery_date": dispatch.delivery_date},
    ).mappings()
    line_records = [dict(row) for row in rows]
    return pl.DataFrame(line_records, schema=EXPORT_LINES_SCHEMA)


def _build_line_sheet(lines: pl.DataFrame) -> pl.DataFrame:
    return lines.select(
        pl.col("fridge").alias(FRIDGE),
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
