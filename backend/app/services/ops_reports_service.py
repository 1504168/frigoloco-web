"""Operations reports: restock (dispatched vs ADDED, #56) and loss (REMOVED x purchase price, #57).

Restock events count only valid tags and are bucketed by their Europe/Brussels local
day (restock report) or local ISO week (loss report). Dispatched quantities come from
dispatch days that actually shipped (dispatched or reconciled).
"""

from __future__ import annotations

import datetime
import io
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import polars as pl
from sqlalchemy import Date, Select, cast, func, select
from sqlalchemy.orm import Session

from app.models.enums import DispatchStatus, RestockAction, TagStatus
from app.models.events import RestockEvent
from app.models.master import Category, Fridge, Product
from app.models.operations import Dispatch, DispatchLine
from app.schemas.ops_reports import (
    LossReportRead,
    LossReportRow,
    RestockReportRead,
    RestockReportRow,
)
from app.services.orders_service import ApiError
from app.services.report_export_service import ExcelDocument

LOCAL_TIMEZONE_NAME = "Europe/Brussels"
LOCAL_TIMEZONE = ZoneInfo(LOCAL_TIMEZONE_NAME)
SHIPPED_DISPATCH_STATUSES = (
    DispatchStatus.dispatched,
    DispatchStatus.reconciled,
)
CENTS_PER_EURO = 100
EURO_FORMAT = "#,##0.00"
RESTOCK_SHEET = "Restock report"
LOSS_SHEET = "Loss report"

DELIVERY_DATE = "delivery_date"
WEEK_START = "week_start"
ISO_YEAR = "iso_year"
ISO_WEEK = "iso_week"
FRIDGE_ID = "fridge_id"
FRIDGE_NAME = "fridge_name"
PRODUCT_ID = "product_id"
PRODUCT_CODE = "product_code"
PRODUCT_NAME = "product_name"
CATEGORY = "category"
UNIT_PURCHASE_PRICE = "unit_purchase_price"
DISPATCHED_QTY = "dispatched_qty"
ADDED_QTY = "added_qty"
GAP_QTY = "gap_qty"
REMOVED_QTY = "removed_qty"
LOSS_COST = "loss_cost"

RESTOCK_KEY = [DELIVERY_DATE, FRIDGE_ID, PRODUCT_ID]

FRIDGE_DETAILS_SCHEMA = {
    FRIDGE_ID: pl.Int64,
    FRIDGE_NAME: pl.Utf8,
}
PRODUCT_DETAILS_SCHEMA = {
    PRODUCT_ID: pl.Int64,
    PRODUCT_CODE: pl.Utf8,
    PRODUCT_NAME: pl.Utf8,
    CATEGORY: pl.Utf8,
    UNIT_PURCHASE_PRICE: pl.Int64,
}

RESTOCK_EXPORT_COLUMNS = {
    DELIVERY_DATE: "Delivery day",
    FRIDGE_NAME: "Fridge",
    CATEGORY: "Category",
    PRODUCT_CODE: "Product code",
    PRODUCT_NAME: "Product",
    DISPATCHED_QTY: "Dispatched qty",
    ADDED_QTY: "Added qty",
    GAP_QTY: "Gap (added - dispatched)",
}
LOSS_EXPORT_COLUMNS = {
    ISO_YEAR: "ISO year",
    ISO_WEEK: "ISO week",
    WEEK_START: "Week start",
    FRIDGE_NAME: "Fridge",
    CATEGORY: "Category",
    PRODUCT_CODE: "Product code",
    PRODUCT_NAME: "Product",
    REMOVED_QTY: "Removed qty",
    UNIT_PURCHASE_PRICE: "Unit purchase price (EUR)",
    LOSS_COST: "Loss cost (EUR)",
}

_LOCAL_EVENT_TIME = func.timezone(LOCAL_TIMEZONE_NAME, RestockEvent.occurred_at)
_LOCAL_EVENT_DAY = cast(_LOCAL_EVENT_TIME, Date)
_LOCAL_EVENT_WEEK_START = cast(func.date_trunc("week", _LOCAL_EVENT_TIME), Date)


@dataclass(frozen=True)
class ReportScope:
    """Inclusive local date range plus the optional fridge / category filters."""

    date_from: datetime.date
    date_to: datetime.date
    fridge_id: int | None = None
    category_id: int | None = None


def load_restock_report(session: Session, scope: ReportScope) -> pl.DataFrame:
    """One row per delivery day x fridge x product with dispatched, added and gap qty."""
    _ensure_valid_range(scope)
    dispatched = _load_dispatched_quantities(session, scope)
    added = _count_valid_restock_events(
        session=session,
        scope=scope,
        action=RestockAction.added,
        period_expression=_LOCAL_EVENT_DAY,
        period_column=DELIVERY_DATE,
        qty_column=ADDED_QTY,
    )
    quantities = combine_dispatched_and_added(dispatched, added)
    return _attach_details(session, quantities).sort(
        DELIVERY_DATE,
        FRIDGE_NAME,
        CATEGORY,
        PRODUCT_NAME,
    )


def combine_dispatched_and_added(
    dispatched: pl.DataFrame,
    added: pl.DataFrame,
) -> pl.DataFrame:
    """Full-join both sides so a product only dispatched, or only added, still shows."""
    return (
        dispatched.join(added, on=RESTOCK_KEY, how="full", coalesce=True)
        .with_columns(
            pl.col(DISPATCHED_QTY).fill_null(0),
            pl.col(ADDED_QTY).fill_null(0),
        )
        .with_columns(
            (pl.col(ADDED_QTY) - pl.col(DISPATCHED_QTY)).alias(GAP_QTY),
        )
    )


def build_restock_report_read(
    report_rows: pl.DataFrame,
    scope: ReportScope,
) -> RestockReportRead:
    rows = [RestockReportRow.model_validate(row) for row in report_rows.to_dicts()]
    return RestockReportRead(
        date_from=scope.date_from,
        date_to=scope.date_to,
        rows=rows,
        total_dispatched_qty=report_rows[DISPATCHED_QTY].sum(),
        total_added_qty=report_rows[ADDED_QTY].sum(),
        total_gap_qty=report_rows[GAP_QTY].sum(),
    )


def build_restock_report_xlsx(
    report_rows: pl.DataFrame,
    scope: ReportScope,
) -> ExcelDocument:
    export_rows = report_rows.select(RESTOCK_EXPORT_COLUMNS.keys()).rename(
        RESTOCK_EXPORT_COLUMNS
    )
    content = _write_sheet(
        export_rows=export_rows,
        sheet_name=RESTOCK_SHEET,
        total_columns=[
            RESTOCK_EXPORT_COLUMNS[DISPATCHED_QTY],
            RESTOCK_EXPORT_COLUMNS[ADDED_QTY],
            RESTOCK_EXPORT_COLUMNS[GAP_QTY],
        ],
        euro_columns=[],
    )
    filename = f"restock-report_{scope.date_from.isoformat()}_{scope.date_to.isoformat()}.xlsx"
    return ExcelDocument(filename=filename, content=content)


def load_loss_report(session: Session, scope: ReportScope) -> pl.DataFrame:
    """One row per local ISO week x fridge x product of valid REMOVED units and their cost."""
    _ensure_valid_range(scope)
    removed = _count_valid_restock_events(
        session=session,
        scope=scope,
        action=RestockAction.removed,
        period_expression=_LOCAL_EVENT_WEEK_START,
        period_column=WEEK_START,
        qty_column=REMOVED_QTY,
    )
    priced_removals = price_removed_units(_attach_details(session, removed))
    return priced_removals.sort(
        WEEK_START,
        FRIDGE_NAME,
        CATEGORY,
        PRODUCT_NAME,
    )


def price_removed_units(removed_with_details: pl.DataFrame) -> pl.DataFrame:
    """Value removed units at the product's current purchase price (cents)."""
    return removed_with_details.with_columns(
        pl.col(WEEK_START).dt.iso_year().alias(ISO_YEAR),
        pl.col(WEEK_START).dt.week().alias(ISO_WEEK),
        (pl.col(REMOVED_QTY) * pl.col(UNIT_PURCHASE_PRICE)).alias(LOSS_COST),
    )


def build_loss_report_read(
    report_rows: pl.DataFrame,
    scope: ReportScope,
) -> LossReportRead:
    rows = [LossReportRow.model_validate(row) for row in report_rows.to_dicts()]
    return LossReportRead(
        date_from=scope.date_from,
        date_to=scope.date_to,
        rows=rows,
        total_removed_qty=report_rows[REMOVED_QTY].sum(),
        total_loss_cost=report_rows[LOSS_COST].sum(),
    )


def build_loss_report_xlsx(
    report_rows: pl.DataFrame,
    scope: ReportScope,
) -> ExcelDocument:
    export_rows = (
        report_rows.with_columns(
            pl.col(UNIT_PURCHASE_PRICE) / CENTS_PER_EURO,
            pl.col(LOSS_COST) / CENTS_PER_EURO,
        )
        .select(LOSS_EXPORT_COLUMNS.keys())
        .rename(LOSS_EXPORT_COLUMNS)
    )
    content = _write_sheet(
        export_rows=export_rows,
        sheet_name=LOSS_SHEET,
        total_columns=[
            LOSS_EXPORT_COLUMNS[REMOVED_QTY],
            LOSS_EXPORT_COLUMNS[LOSS_COST],
        ],
        euro_columns=[
            LOSS_EXPORT_COLUMNS[UNIT_PURCHASE_PRICE],
            LOSS_EXPORT_COLUMNS[LOSS_COST],
        ],
    )
    filename = f"loss-report_{scope.date_from.isoformat()}_{scope.date_to.isoformat()}.xlsx"
    return ExcelDocument(filename=filename, content=content)


def _ensure_valid_range(scope: ReportScope) -> None:
    if scope.date_to < scope.date_from:
        raise ApiError(422, "unprocessable_entity", "date_to cannot precede date_from")


def _load_dispatched_quantities(session: Session, scope: ReportScope) -> pl.DataFrame:
    statement = (
        select(
            DispatchLine.delivery_date,
            DispatchLine.fridge_id,
            DispatchLine.product_id,
            func.sum(DispatchLine.qty),
        )
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .where(
            Dispatch.status.in_(SHIPPED_DISPATCH_STATUSES),
            DispatchLine.delivery_date >= scope.date_from,
            DispatchLine.delivery_date <= scope.date_to,
        )
        .group_by(
            DispatchLine.delivery_date,
            DispatchLine.fridge_id,
            DispatchLine.product_id,
        )
    )
    scoped_statement = _apply_scope_filters(
        statement=statement,
        fridge_column=DispatchLine.fridge_id,
        product_column=DispatchLine.product_id,
        scope=scope,
    )
    return _read_frame(
        session=session,
        statement=scoped_statement,
        schema=_quantity_schema(DELIVERY_DATE, DISPATCHED_QTY),
    )


def _count_valid_restock_events(
    session: Session,
    scope: ReportScope,
    action: RestockAction,
    period_expression,
    period_column: str,
    qty_column: str,
) -> pl.DataFrame:
    window_start = datetime.datetime.combine(
        scope.date_from,
        datetime.time.min,
        tzinfo=LOCAL_TIMEZONE,
    )
    window_end = datetime.datetime.combine(
        scope.date_to + datetime.timedelta(days=1),
        datetime.time.min,
        tzinfo=LOCAL_TIMEZONE,
    )
    statement = (
        select(
            period_expression,
            RestockEvent.fridge_id,
            RestockEvent.product_id,
            func.count(),
        )
        .where(
            RestockEvent.occurred_at >= window_start,
            RestockEvent.occurred_at < window_end,
            RestockEvent.action == action,
            RestockEvent.tag_status == TagStatus.valid,
        )
        .group_by(
            period_expression,
            RestockEvent.fridge_id,
            RestockEvent.product_id,
        )
    )
    scoped_statement = _apply_scope_filters(
        statement=statement,
        fridge_column=RestockEvent.fridge_id,
        product_column=RestockEvent.product_id,
        scope=scope,
    )
    return _read_frame(
        session=session,
        statement=scoped_statement,
        schema=_quantity_schema(period_column, qty_column),
    )


def _apply_scope_filters(
    statement: Select,
    fridge_column,
    product_column,
    scope: ReportScope,
) -> Select:
    if scope.fridge_id is not None:
        statement = statement.where(fridge_column == scope.fridge_id)
    if scope.category_id is not None:
        statement = statement.join(Product, Product.id == product_column).where(
            Product.category_id == scope.category_id
        )
    return statement


def _attach_details(session: Session, quantities: pl.DataFrame) -> pl.DataFrame:
    """Join fridge names and product code / name / category / purchase price by id."""
    fridge_ids = quantities[FRIDGE_ID].unique().to_list()
    product_ids = quantities[PRODUCT_ID].unique().to_list()
    fridges = _read_frame(
        session=session,
        statement=select(Fridge.id, Fridge.friendly_name).where(Fridge.id.in_(fridge_ids)),
        schema=FRIDGE_DETAILS_SCHEMA,
    )
    products = _read_frame(
        session=session,
        statement=(
            select(
                Product.id,
                Product.code,
                Product.name,
                Category.name,
                Product.purchase_price,
            )
            .join(Category, Category.id == Product.category_id)
            .where(Product.id.in_(product_ids))
        ),
        schema=PRODUCT_DETAILS_SCHEMA,
    )
    return quantities.join(fridges, on=FRIDGE_ID).join(products, on=PRODUCT_ID)


def _quantity_schema(period_column: str, qty_column: str) -> dict[str, pl.DataType]:
    return {
        period_column: pl.Date,
        FRIDGE_ID: pl.Int64,
        PRODUCT_ID: pl.Int64,
        qty_column: pl.Int64,
    }


def _read_frame(
    session: Session,
    statement: Select,
    schema: dict[str, pl.DataType],
) -> pl.DataFrame:
    records = session.execute(statement).all()
    return pl.DataFrame(records, schema=schema, orient="row")


def _write_sheet(
    export_rows: pl.DataFrame,
    sheet_name: str,
    total_columns: list[str],
    euro_columns: list[str],
) -> bytes:
    buffer = io.BytesIO()
    euro_formats = dict.fromkeys(euro_columns, EURO_FORMAT)
    export_rows.write_excel(
        workbook=buffer,
        worksheet=sheet_name,
        autofit=True,
        column_formats=euro_formats,
        column_totals=total_columns,
    )
    return buffer.getvalue()
