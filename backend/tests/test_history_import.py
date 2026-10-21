"""Excel history importer: cell parsing, fridge/product mapping, plan rules, replace rule.

Pure tests: the plan is built from hand-made rows and an in-memory catalogue, so
nothing touches the database.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from app.models.enums import DispatchStatus, PoStatus
from scripts.history_import.database import (
    ExistingAction,
    ExistingRecord,
    classify_existing,
)
from scripts.history_import.plan import (
    Catalogue,
    CatalogueProduct,
    DropReason,
    ImportPlan,
    build_import_plan,
    confirmation_time,
    highest_order_sequence_by_year,
    resolve_fridge_name,
    resolve_product_code,
)
from scripts.history_import.workbook import (
    DispatchRow,
    DispatchSaveRow,
    OrderHeaderRow,
    OrderLineRow,
    TableRow,
    TargetRow,
    WorkbookHistory,
    clean_code,
    compute_delivery_date,
    excel_flag,
    parse_dispatch_saves,
    whole_number,
)

MONDAY = datetime.date(2026, 3, 23)
WEDNESDAY = datetime.date(2026, 3, 25)
IMPORT_DATE = datetime.date(2026, 10, 21)
VAT = Decimal("0.0600")
SANDWICH_CODE = "0000024838979"
COLA_CODE = "0000073729082"

SANDWICH = CatalogueProduct(id=1, purchase_price=500, sales_price=900, vat_rate=VAT)
COLA = CatalogueProduct(id=2, purchase_price=60, sales_price=200, vat_rate=VAT)
CATALOGUE = Catalogue(
    products_by_code={
        SANDWICH_CODE: SANDWICH,
        COLA_CODE: COLA,
    },
    product_ids_by_name={
        "sandwich": [1],
        "cola": [2],
    },
    fridge_names={
        "CBC",
        "Velux",
        "Greenhouse Collection Links",
    },
    supplier_id_by_name={"Croc&Go": 7},
)


def test_compute_delivery_date_adds_day_offset_and_fixes_known_typo():
    week_start = datetime.datetime(2026, 3, 23)

    assert compute_delivery_date(week_start, "Wednesday") == WEDNESDAY
    assert compute_delivery_date(week_start, " Wednesay ") == WEDNESDAY


def test_dispatch_saves_skip_rows_without_dates_or_day_names():
    week_start = datetime.datetime(2026, 3, 23)
    saved_at = datetime.datetime(2026, 3, 20, 16, 57)
    rows = [
        _save_table_row(week_start=week_start, day_name="Wednesay", saved_at=saved_at),
        _save_table_row(week_start=week_start, day_name="Week 35", saved_at=saved_at),
        _save_table_row(week_start=None, day_name="Monday", saved_at=saved_at),
    ]

    saves = parse_dispatch_saves(rows)

    assert saves == [DispatchSaveRow(delivery_date=WEDNESDAY, last_saved_local=saved_at)]


def test_clean_code_keeps_text_codes_and_strips_tabs():
    assert clean_code(2157) == "2157"
    assert clean_code(2157.0) == "2157"
    assert clean_code("\t0000073729082") == COLA_CODE
    assert clean_code(None) == ""


def test_whole_number_rejects_fractions_and_blank_is_zero():
    assert whole_number(None) == 0
    assert whole_number(3.0) == 3
    with pytest.raises(ValueError):
        whole_number(1.5)


def test_excel_flag_rejects_non_boolean_cells():
    assert excel_flag(True) is True
    with pytest.raises(TypeError):
        excel_flag("True")


def test_fridge_mapping_aliases_placeholders_and_undecided_names():
    assert resolve_fridge_name("Velux", CATALOGUE) == "Velux"
    assert resolve_fridge_name("CBC Namur", CATALOGUE) == "CBC"
    assert resolve_fridge_name("ATELIER", CATALOGUE) == "Atelier rue du Cerf"
    assert resolve_fridge_name("Echantillons", CATALOGUE) == "Echantillons"
    assert resolve_fridge_name("CBC", CATALOGUE) is None
    assert resolve_fridge_name("Nowhere", CATALOGUE) is None


def test_product_code_resolves_exact_then_zero_padded():
    assert resolve_product_code(SANDWICH_CODE, CATALOGUE) == SANDWICH
    assert resolve_product_code("24838979", CATALOGUE) == SANDWICH
    assert resolve_product_code("999", CATALOGUE) is None


def test_dispatch_plan_groups_by_delivery_date_and_sums_duplicate_lines():
    rows = [
        _dispatch_row(row_number=5, quantity=2),
        _dispatch_row(row_number=6, quantity=3),
        _dispatch_row(row_number=7, quantity=0),
        _dispatch_row(row_number=8, delivery_date=WEDNESDAY, is_dispatched=False),
    ]

    plan = _plan(dispatch_rows=rows)

    monday, wednesday = plan.dispatches
    assert monday.delivery_date == MONDAY
    assert monday.status is DispatchStatus.dispatched
    assert [line.qty for line in monday.lines] == [5]
    assert wednesday.status is DispatchStatus.saved
    assert wednesday.confirmed_at is None
    assert _drop_reasons(plan) == [DropReason.NON_POSITIVE_QTY]


def test_mixed_dispatched_flags_on_one_day_fail_loudly():
    rows = [
        _dispatch_row(row_number=5, is_dispatched=True),
        _dispatch_row(row_number=6, is_dispatched=False),
    ]

    with pytest.raises(ValueError):
        _plan(dispatch_rows=rows)


def test_unresolved_fridge_rows_are_counted_and_placeholders_listed():
    rows = [
        _dispatch_row(row_number=5, fridge_name="CBC"),
        _dispatch_row(row_number=6, fridge_name="CBC Namur"),
        _dispatch_row(row_number=7, fridge_name="PWC Antwerpen"),
    ]

    plan = _plan(dispatch_rows=rows)

    assert plan.unresolved_fridge_rows == {"CBC": 1}
    assert plan.placeholder_fridges_to_create(CATALOGUE) == ["PWC Antwerpen"]
    fridge_names = sorted(line.fridge_name for line in plan.dispatches[0].lines)
    assert fridge_names == ["CBC", "PWC Antwerpen"]


def test_blank_code_repaired_from_same_name_and_priced_from_same_week():
    rows = [
        _dispatch_row(row_number=5, purchase_price=510, sales_price=950),
        _dispatch_row(
            row_number=6,
            delivery_date=WEDNESDAY,
            fridge_name="CBC Namur",
            product_code="",
            purchase_price=0,
            sales_price=0,
        ),
        _dispatch_row(row_number=7, product_code="", product_name="Mystery salad"),
    ]

    plan = _plan(dispatch_rows=rows)

    repaired_line = plan.dispatches[1].lines[0]
    assert repaired_line.product_id == SANDWICH.id
    assert repaired_line.unit_purchase_price == 510
    assert repaired_line.unit_sales_price == 950
    assert [repaired.row_count for repaired in plan.repaired_codes] == [1]
    assert _drop_reasons(plan) == [DropReason.BLANK_CODE_NOT_REPAIRABLE]


def test_blank_code_without_same_week_row_takes_catalogue_price():
    rows = [
        _dispatch_row(row_number=5, delivery_date=MONDAY),
        _dispatch_row(
            row_number=6,
            delivery_date=MONDAY + datetime.timedelta(days=7),
            product_code="",
            purchase_price=0,
            sales_price=0,
        ),
    ]

    plan = _plan(dispatch_rows=rows)

    repaired_line = plan.dispatches[1].lines[0]
    assert repaired_line.unit_purchase_price == SANDWICH.purchase_price
    assert repaired_line.unit_sales_price == SANDWICH.sales_price


def test_confirmation_time_converts_brussels_save_time_to_utc():
    saved_local = datetime.datetime(2026, 7, 6, 14, 30)
    saved_by_date = {MONDAY: saved_local}

    assert confirmation_time(MONDAY, saved_by_date) == datetime.datetime(
        2026, 7, 6, 12, 30, tzinfo=datetime.UTC
    )
    assert confirmation_time(WEDNESDAY, saved_by_date) == datetime.datetime(
        2026, 3, 24, 23, 0, tzinfo=datetime.UTC
    )


def test_old_pending_order_becomes_received_and_recent_stays_pending():
    headers = [
        _order_header(order_no="2026-00001", expected=datetime.date(2026, 10, 6)),
        _order_header(order_no="2026-00002", expected=datetime.date(2026, 10, 8)),
        _order_header(order_no="2026-00003", status_text="Cancelled"),
    ]
    lines = [
        _order_line(order_no="2026-00001"),
        _order_line(order_no="2026-00002"),
        _order_line(order_no="2026-00003"),
    ]

    plan = _plan(order_headers=headers, order_lines=lines)

    statuses = {order.order_no: order.status for order in plan.orders}
    assert statuses == {
        "2026-00001": PoStatus.received,
        "2026-00002": PoStatus.pending,
        "2026-00003": PoStatus.cancelled,
    }


def test_order_lines_dropped_summed_and_totals_computed_in_cents():
    headers = [_order_header(order_no="2026-00010")]
    lines = [
        _order_line(order_no="2026-00010", qty_ordered=10, unit_price=388),
        _order_line(order_no="2026-00010", qty_ordered=5, unit_price=388, qty_received=-2),
        _order_line(order_no="2026-00010", qty_ordered=0),
        _order_line(order_no="2026-00099"),
    ]

    plan = _plan(order_headers=headers, order_lines=lines)

    (order,) = plan.orders
    (line,) = order.lines
    assert line.qty_ordered == 15
    assert line.qty_received == 0
    assert order.total_ex_vat == 5820
    assert order.total_vat == 349
    assert order.total_incl_vat == 6169
    assert sorted(_drop_reasons(plan)) == sorted(
        [DropReason.NON_POSITIVE_QTY, DropReason.LINE_WITHOUT_ORDER]
    )


def test_order_with_unknown_supplier_is_not_planned():
    headers = [_order_header(order_no="2026-00011", supplier_name="Unknown Foods")]
    lines = [_order_line(order_no="2026-00011")]

    plan = _plan(order_headers=headers, order_lines=lines)

    assert plan.orders == []
    assert plan.unknown_supplier_orders == {"Unknown Foods": 1}


def test_targets_map_fridges_and_drop_duplicates():
    targets = [
        TargetRow(
            row_number=4,
            fridge_name="CBC Namur",
            product_code=COLA_CODE,
            product_name="Cola",
            target_qty=5,
        ),
        TargetRow(
            row_number=5,
            fridge_name="CBC Namur",
            product_code=COLA_CODE,
            product_name="Cola",
            target_qty=6,
        ),
    ]

    plan = _plan(targets=targets)

    (target,) = plan.targets
    assert target.fridge_name == "CBC"
    assert target.target_qty == 5
    assert _drop_reasons(plan) == [DropReason.DUPLICATE_TARGET]


def test_highest_order_sequence_per_year():
    order_numbers = [
        "2025-00153",
        "2026-00002",
        "2026-00531",
    ]

    assert highest_order_sequence_by_year(order_numbers) == {2025: 153, 2026: 531}


@pytest.mark.parametrize(
    ("is_imported", "stock_movement_count", "expected_action"),
    [
        (True, 0, ExistingAction.REPLACE),
        (True, 1, ExistingAction.COLLISION),
        (False, 0, ExistingAction.COLLISION),
    ],
)
def test_only_imported_rows_without_stock_movements_are_replaced(
    is_imported: bool,
    stock_movement_count: int,
    expected_action: ExistingAction,
):
    record = ExistingRecord(
        id=1,
        key="2026-07-10",
        status="saved",
        is_imported=is_imported,
        line_count=2,
        stock_movement_count=stock_movement_count,
    )

    assert classify_existing(record) is expected_action


def _plan(
    dispatch_rows: list[DispatchRow] | None = None,
    dispatch_saves: list[DispatchSaveRow] | None = None,
    order_headers: list[OrderHeaderRow] | None = None,
    order_lines: list[OrderLineRow] | None = None,
    targets: list[TargetRow] | None = None,
) -> ImportPlan:
    history = WorkbookHistory(
        dispatch_rows=dispatch_rows or [],
        dispatch_saves=dispatch_saves or [],
        order_headers=order_headers or [],
        order_lines=order_lines or [],
        targets=targets or [],
    )
    return build_import_plan(history, CATALOGUE, IMPORT_DATE)


def _save_table_row(
    week_start: datetime.datetime | None,
    day_name: str,
    saved_at: datetime.datetime,
) -> TableRow:
    values = {
        "Week Start Date": week_start,
        "Dispatch Day": day_name,
        "Last Saved Time": saved_at,
    }
    return TableRow(row_number=5, values=values)


def _dispatch_row(
    row_number: int,
    delivery_date: datetime.date = MONDAY,
    fridge_name: str = "Velux",
    product_code: str = SANDWICH_CODE,
    product_name: str = "Sandwich",
    quantity: int = 1,
    purchase_price: int = 500,
    sales_price: int = 900,
    is_dispatched: bool = True,
) -> DispatchRow:
    return DispatchRow(
        row_number=row_number,
        delivery_date=delivery_date,
        fridge_name=fridge_name,
        product_code=product_code,
        product_name=product_name,
        quantity=quantity,
        purchase_price=purchase_price,
        sales_price=sales_price,
        vat_rate=VAT,
        is_dispatched=is_dispatched,
    )


def _order_header(
    order_no: str,
    expected: datetime.date = IMPORT_DATE,
    status_text: str = " Pending ",
    supplier_name: str = "Croc&Go",
) -> OrderHeaderRow:
    return OrderHeaderRow(
        row_number=5,
        order_no=order_no,
        supplier_name=supplier_name,
        comment=None,
        order_date=datetime.date(2026, 10, 1),
        expected_delivery_date=expected,
        delivery_address=None,
        workbook_total_incl_vat=0,
        status_text=status_text.strip(),
    )


def _order_line(
    order_no: str,
    qty_ordered: int = 1,
    unit_price: int = 100,
    qty_received: int = 0,
) -> OrderLineRow:
    return OrderLineRow(
        row_number=5,
        order_no=order_no,
        product_code=SANDWICH_CODE,
        product_name="Sandwich",
        unit_price=unit_price,
        vat_rate=VAT,
        qty_ordered=qty_ordered,
        qty_received=qty_received,
    )


def _drop_reasons(plan: ImportPlan) -> list[DropReason]:
    return [dropped.reason for dropped in plan.dropped_rows]
