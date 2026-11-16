"""Excel export builders for the finance reports (one fridge, all fridges).

Each workbook is built in two passes:

* **Polars** ``DataFrame.write_excel`` renders the table body as a proper Excel
  table, anchored a few rows down to leave the top of the sheet free.
* **openpyxl** re-opens that workbook and writes the summary block (title,
  period and the KPI figures) into the reserved top rows, so the summary reads
  first and the table follows below it.

Keeping the two engines in separate passes (Polars writes, openpyxl decorates)
avoids mixing incompatible workbook objects and yields a plain ``.xlsx`` any
consumer - including openpyxl itself - can open.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import polars as pl
from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from app.money import cents_to_euro_decimal
from app.services.finance_service import (
    AllFridgesReportData,
    FridgeReportData,
    ReportFigures,
)

_FRIDGE_SHEET_NAME = "Fridge Report"
_ALL_FRIDGES_SHEET_NAME = "All Fridges Report"
# The table body starts here; rows 1..10 are reserved for the summary block.
_TABLE_ANCHOR = "A11"
_FIRST_KPI_ROW = 5
_TABLE_STYLE = "Table Style Medium 9"
_EURO_FORMAT = "#,##0.00"
_QTY_FORMAT = "#,##0"
_PERCENT_FORMAT = "0.0%"
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Ratios travel through the app as 0..1 fractions; only this display edge shows
# them in percent units.
_PERCENT_SCALE = Decimal("100")
_PERCENT_QUANTUM = Decimal("0.01")

_ADDED_QTY = "Added Qty"
_UNIT_BUYING_PRICE = "Unit Buying Price (EUR)"
_UNIT_SELLING_PRICE = "Unit Selling Price (EUR)"
_FOOD_COST = "Food Cost (EUR)"
_REVENUE = "Revenue incl VAT (EUR)"
_REVENUE_EX_VAT = "Revenue ex VAT (EUR)"
_FOOD_MARGIN = "Food Margin (EUR)"
_FOOD_MARGIN_PCT = "Food Margin %"

_ALL_FRIDGES_SUMMED_COLUMNS = [
    _ADDED_QTY,
    _FOOD_COST,
    _REVENUE,
    _REVENUE_EX_VAT,
    _FOOD_MARGIN,
]


@dataclass(frozen=True)
class ExcelDocument:
    """A rendered workbook plus its download filename."""

    filename: str
    content: bytes

    @property
    def media_type(self) -> str:
        return _XLSX_MEDIA_TYPE


@dataclass(frozen=True)
class _Kpi:
    label: str
    value: object
    number_format: str | None


def build_fridge_report_xlsx(data: FridgeReportData) -> ExcelDocument:
    """Render the fridge report to a streamable ``.xlsx`` document."""
    frame = pl.DataFrame(
        {
            "Product": [row.name for row in data.rows],
            "Code": [row.code for row in data.rows],
            "Category": [row.category or "" for row in data.rows],
            _ADDED_QTY: [row.added_qty for row in data.rows],
            _UNIT_BUYING_PRICE: [_euro(row.unit_buying_price) for row in data.rows],
            _UNIT_SELLING_PRICE: [_euro(row.unit_selling_price) for row in data.rows],
        },
        schema={
            "Product": pl.Utf8,
            "Code": pl.Utf8,
            "Category": pl.Utf8,
            _ADDED_QTY: pl.Int64,
            _UNIT_BUYING_PRICE: pl.Float64,
            _UNIT_SELLING_PRICE: pl.Float64,
        },
    )
    figures = data.figures
    # The existing layout keeps "Revenue (EUR)" (incl. VAT) in place; ex-VAT revenue
    # is appended last so earlier KPI rows do not move.
    kpis = [
        _Kpi("Total Added Qty", figures.added_qty, _QTY_FORMAT),
        _Kpi("Food Cost (EUR)", _euro(figures.food_cost), _EURO_FORMAT),
        _Kpi("Revenue (EUR)", _euro(figures.revenue), _EURO_FORMAT),
        _Kpi("Food Margin (EUR)", _euro(figures.margin), _EURO_FORMAT),
        _Kpi("Food Margin %", _percent_text(figures.margin_pct), None),
        _Kpi("Revenue ex VAT (EUR)", _euro(figures.revenue_ex_vat), _EURO_FORMAT),
    ]

    def write_summary(worksheet: Worksheet) -> None:
        _write_title(worksheet, "Fridge Report")
        _write_label_value(worksheet, 2, "Fridge", f"{data.fridge_name} (#{data.fridge_id})")
        _write_label_value(worksheet, 3, "Period", _period_text(data))
        _write_kpis(worksheet, kpis)

    content = _render_workbook(
        frame=frame,
        sheet_name=_FRIDGE_SHEET_NAME,
        column_formats={
            _ADDED_QTY: _QTY_FORMAT,
            _UNIT_BUYING_PRICE: _EURO_FORMAT,
            _UNIT_SELLING_PRICE: _EURO_FORMAT,
        },
        column_totals=None,
        write_summary=write_summary,
    )
    filename = (
        f"fridge-report_{data.fridge_id}_"
        f"{data.date_from.isoformat()}_{data.date_to.isoformat()}.xlsx"
    )
    return ExcelDocument(filename=filename, content=content)


def build_all_fridges_report_xlsx(data: AllFridgesReportData) -> ExcelDocument:
    """Render the all-fridges report: totals on top, one row per fridge below."""
    frame = pl.DataFrame(
        {
            "Fridge": [row.fridge_name for row in data.rows],
            "Client": [row.client_name for row in data.rows],
            _ADDED_QTY: [row.figures.added_qty for row in data.rows],
            _FOOD_COST: [_euro(row.figures.food_cost) for row in data.rows],
            _REVENUE: [_euro(row.figures.revenue) for row in data.rows],
            _REVENUE_EX_VAT: [_euro(row.figures.revenue_ex_vat) for row in data.rows],
            _FOOD_MARGIN: [_euro(row.figures.margin) for row in data.rows],
            _FOOD_MARGIN_PCT: [_fraction(row.figures.margin_pct) for row in data.rows],
        },
        schema={
            "Fridge": pl.Utf8,
            "Client": pl.Utf8,
            _ADDED_QTY: pl.Int64,
            _FOOD_COST: pl.Float64,
            _REVENUE: pl.Float64,
            _REVENUE_EX_VAT: pl.Float64,
            _FOOD_MARGIN: pl.Float64,
            _FOOD_MARGIN_PCT: pl.Float64,
        },
    )

    def write_summary(worksheet: Worksheet) -> None:
        _write_title(worksheet, "All Fridges Report")
        _write_label_value(worksheet, 2, "Period", _period_text(data))
        _write_label_value(worksheet, 3, "Fridges", len(data.rows))
        _write_kpis(worksheet, _totals_kpis(data.totals))

    content = _render_workbook(
        frame=frame,
        sheet_name=_ALL_FRIDGES_SHEET_NAME,
        column_formats={
            _ADDED_QTY: _QTY_FORMAT,
            _FOOD_COST: _EURO_FORMAT,
            _REVENUE: _EURO_FORMAT,
            _REVENUE_EX_VAT: _EURO_FORMAT,
            _FOOD_MARGIN: _EURO_FORMAT,
            _FOOD_MARGIN_PCT: _PERCENT_FORMAT,
        },
        column_totals=_ALL_FRIDGES_SUMMED_COLUMNS,
        write_summary=write_summary,
    )
    filename = (
        f"all-fridges-report_{data.date_from.isoformat()}_{data.date_to.isoformat()}.xlsx"
    )
    return ExcelDocument(filename=filename, content=content)


def _render_workbook(
    *,
    frame: pl.DataFrame,
    sheet_name: str,
    column_formats: dict[str, str],
    column_totals: list[str] | None,
    write_summary: Callable[[Worksheet], None],
) -> bytes:
    table_buffer = io.BytesIO()
    frame.write_excel(
        table_buffer,
        worksheet=sheet_name,
        position=_TABLE_ANCHOR,
        table_style=_TABLE_STYLE,
        autofit=True,
        column_formats=column_formats,
        column_totals=column_totals,
    )
    table_buffer.seek(0)
    workbook = load_workbook(table_buffer)
    write_summary(workbook[sheet_name])

    workbook_buffer = io.BytesIO()
    workbook.save(workbook_buffer)
    return workbook_buffer.getvalue()


def _totals_kpis(totals: ReportFigures) -> list[_Kpi]:
    return [
        _Kpi("Total Added Qty", totals.added_qty, _QTY_FORMAT),
        _Kpi(_FOOD_COST, _euro(totals.food_cost), _EURO_FORMAT),
        _Kpi(_REVENUE, _euro(totals.revenue), _EURO_FORMAT),
        _Kpi(_REVENUE_EX_VAT, _euro(totals.revenue_ex_vat), _EURO_FORMAT),
        _Kpi(_FOOD_MARGIN, _euro(totals.margin), _EURO_FORMAT),
        _Kpi(_FOOD_MARGIN_PCT, _percent_text(totals.margin_pct), None),
    ]


def _write_title(worksheet: Worksheet, title: str) -> None:
    worksheet["A1"] = title
    worksheet["A1"].font = Font(bold=True, size=14)


def _write_label_value(worksheet: Worksheet, row_no: int, label: str, value: object) -> None:
    label_cell = worksheet.cell(row=row_no, column=1, value=label)
    label_cell.font = Font(bold=True)
    worksheet.cell(row=row_no, column=2, value=value)


def _write_kpis(worksheet: Worksheet, kpis: list[_Kpi]) -> None:
    for index, kpi in enumerate(kpis):
        row_no = _FIRST_KPI_ROW + index
        _write_label_value(worksheet, row_no, kpi.label, kpi.value)
        if kpi.number_format is not None:
            worksheet.cell(row=row_no, column=2).number_format = kpi.number_format


def _period_text(data: FridgeReportData | AllFridgesReportData) -> str:
    return f"{data.date_from.isoformat()} → {data.date_to.isoformat()}"


def _euro(cents: int) -> float:
    """Cents to euros as a float for a numeric Excel cell."""
    return float(cents_to_euro_decimal(cents))


def _fraction(fraction: Decimal | None) -> float | None:
    if fraction is None:
        return None
    return float(fraction)


def _percent_text(fraction: Decimal | None) -> str:
    """A 0..1 fraction as a 2-decimal percentage string (0.6000 -> "60.00%")."""
    if fraction is None:
        return "n/a"
    return f"{(fraction * _PERCENT_SCALE).quantize(_PERCENT_QUANTUM)}%"
