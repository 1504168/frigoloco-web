"""Pure (no database) tests: the printable dispatch workbook and fit to stock with orders."""

from __future__ import annotations

import datetime
import io

import polars as pl
from openpyxl import load_workbook

from app.services.dispatch_export_service import (
    EXPORT_LINES_SCHEMA,
    TABLE_HEADER_ROW,
    render_dispatch_workbook,
)
from app.services.stock_fit_service import StockFitLine, fit_lines_to_stock

DELIVERY_DATE = datetime.date(2026, 11, 17)
PRODUCT_A = 1
PRODUCT_B = 2


def _export_line(
    fridge: str,
    client: str,
    category: str,
    print_order: int,
    name: str,
    qty: int,
) -> dict[str, object]:
    return {
        "fridge": fridge,
        "client": client,
        "category": category,
        "category_print_order": print_order,
        "supplier": "Supplier",
        "product_code": f"C-{name}",
        "product_name": name,
        "qty": qty,
        "unit_purchase_cents": 150,
        "unit_sales_cents": 400,
        "vat_rate": 0.06,
    }


def test_workbook_has_one_printable_pick_list_per_fridge_without_prices():
    export_lines = pl.DataFrame(
        [
            _export_line("Zeta office", "Acme", "Desserts", 8, "Tiramisu", 2),
            _export_line("Zeta office", "Acme", "Warm", 1, "Lasagne", 5),
            _export_line("Zeta office", "Acme", "Warm", 1, "Curry", 3),
            _export_line("Alpha lab", "Beta Corp", "Warm", 1, "Curry", 4),
        ],
        schema=EXPORT_LINES_SCHEMA,
    )

    workbook = load_workbook(io.BytesIO(render_dispatch_workbook(export_lines, DELIVERY_DATE)))

    assert workbook.sheetnames == [
        "Summary",
        "Zeta office",
        "Alpha lab",
        "Dispatch lines",
        "Fridge x Product",
    ]
    pick_list = workbook["Zeta office"]
    assert pick_list["A1"].value == "Zeta office"
    assert pick_list["A2"].value == "Client: Acme"
    assert pick_list["A3"].value == "Delivery: Tuesday 17 November 2026"
    table_rows = list(pick_list.iter_rows(min_row=TABLE_HEADER_ROW, values_only=True))
    assert table_rows == [
        ("Product code", "Product", "Qty", "Packed"),
        ("Warm (8 units)", None, None, None),
        ("C-Curry", "Curry", 3, None),
        ("C-Lasagne", "Lasagne", 5, None),
        ("Desserts (2 units)", None, None, None),
        ("C-Tiramisu", "Tiramisu", 2, None),
        ("Total", "3 products", 10, None),
    ]
    assert pick_list.cell(row=TABLE_HEADER_ROW + 2, column=3).font.bold
    assert pick_list.print_title_rows == f"${TABLE_HEADER_ROW}:${TABLE_HEADER_ROW}"
    assert pick_list.page_setup.orientation == "portrait"
    assert pick_list.page_setup.fitToWidth == 1
    assert pick_list.print_options.gridLines

    summary_rows = list(
        workbook["Summary"].iter_rows(min_row=TABLE_HEADER_ROW + 1, values_only=True)
    )
    assert summary_rows == [
        ("Acme", "Zeta office", 3, 10),
        ("Beta Corp", "Alpha lab", 1, 4),
        ("Total", None, 4, 14),
    ]


def test_fit_with_orders_reports_the_units_only_orders_cover():
    lines = [
        StockFitLine(fridge_id=1, product_id=PRODUCT_A, qty=6),
        StockFitLine(fridge_id=2, product_id=PRODUCT_A, qty=4),
        StockFitLine(fridge_id=1, product_id=PRODUCT_B, qty=3),
    ]

    stock_fit = fit_lines_to_stock(
        lines,
        physical_stock={PRODUCT_A: 2, PRODUCT_B: 1},
        ordered_stock={PRODUCT_A: 3, PRODUCT_B: 5},
    )

    assert [line.qty for line in stock_fit.lines] == [3, 2, 3]
    assert [(cut.product_id, cut.in_stock, cut.on_order) for cut in stock_fit.cuts] == [
        (PRODUCT_A, 5, 3),
    ]
    order_units = {use.product_id: use.units_from_orders for use in stock_fit.order_uses}
    assert order_units == {PRODUCT_A: 3, PRODUCT_B: 2}
