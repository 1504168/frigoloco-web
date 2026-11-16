"""Finance domain logic (R10/R11/R12): weekly P&L, live monthly analysis by
client/fridge/supplier/category, and fridge reports (one fridge or all fridges).

Verified formulas (IMPLEMENTATION-BRIEF): sales turnover ex-VAT =
``(gross + credit - refunds) / 1.06``; POS fee = 9% of VAT-INCLUSIVE gross;
RFID fee = rate x items_sold; weekly food cost uses the ADDED (restock) basis;
monthly food margin uses the DISPATCHED basis (dispatched/reconciled only).
Week, month and report-day windows are Europe/Brussels calendar days.
"""

from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.models.enums import DispatchStatus, RestockAction, TagStatus
from app.models.events import RestockEvent, SalesEvent
from app.models.master import (
    Category,
    Client,
    ClientFee,
    ClientServiceCharge,
    Fridge,
    FridgeProductPrice,
    Product,
    Setting,
    Supplier,
)
from app.models.operations import Dispatch, DispatchLine, WeeklyFinancial
from app.models.planning import ProductScore
from app.money import to_cents
from app.schemas.finance import (
    AllFridgesReportRead,
    AllFridgesReportRow,
    FridgeReportRead,
    FridgeReportRow,
    MonthlyAnalysisRead,
    MonthlyAnalysisRow,
    WeeklyFinancialInputs,
    WeeklyInputsRead,
    WeeklyPnlRead,
)
from app.services import scoring_service
from app.services.orders_service import ApiError, write_audit

# One divisor for all sales: assumes every product carries 6% food VAT (open question:
# drinks at 21% would need a per-product VAT split).
VAT_DIVISOR = Decimal("1.06")
DEFAULT_POS_FEE_PCT = Decimal("0.09")  # fraction (NOT money)
# RFID fee is money in cents now: EUR 0.10 -> 10 cents per item sold.
DEFAULT_RFID_FEE_RATE = Decimal("10")

# Finance periods follow the business calendar, not UTC: a Sunday-evening sale
# belongs to that week, not the next one.
LOCAL_TIMEZONE = ZoneInfo("Europe/Brussels")

DAYS_PER_WEEK = 7
MONTHS_PER_YEAR = Decimal(12)
ZERO = Decimal(0)
NO_CLIENT_NAME = "No client"
NO_ACTIVE_FRIDGE_SUFFIX = "(no active fridge)"
TOTAL_ROW_NAME = "Total"

# Only dispatches that physically left the warehouse count towards food margin.
MARGIN_DISPATCH_STATUSES = (DispatchStatus.dispatched, DispatchStatus.reconciled)

MONTHLY_DIMENSIONS = ("client", "fridge", "supplier", "category")

# Every ratio the service emits (margin, %sold, review, scores) is a plain 0..1
# fraction quantized to four decimal places.
_FOUR_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class DateWindow:
    start: datetime.datetime
    end: datetime.datetime


@dataclass(frozen=True)
class _SalesTotals:
    sales: Decimal
    items: int


_NO_SALES = _SalesTotals(sales=ZERO, items=0)


@dataclass(frozen=True)
class _FridgeRef:
    fridge_id: int
    name: str
    client_id: int | None
    is_active: bool


@dataclass(frozen=True)
class _ClientMonthCosts:
    """Client-level monthly amounts that the client and fridge views allocate."""

    fee_share_by_client: dict[int, Decimal]
    service_by_client: dict[int, Decimal]
    logistics_per_active_fridge: Decimal
    client_names: dict[int, str]
    fridges: list[_FridgeRef]


@dataclass(frozen=True)
class _ClientCostAmounts:
    sales: Decimal
    food_margin: Decimal
    fee_share: Decimal
    service_additionals: Decimal
    logistics_share: Decimal


@dataclass(frozen=True)
class _MonthlyRowLabel:
    key_id: int | None
    key_name: str
    client_name: str | None
    fridge_count: int | None


@dataclass(frozen=True)
class FridgeReportRowData:
    """One product line of the fridge report (money fields are integer cents)."""

    product_id: int
    code: str
    name: str
    category: str | None
    added_qty: int
    unit_buying_price: int
    unit_selling_price: int


@dataclass(frozen=True)
class ReportFigures:
    """Summary KPIs of a fridge report (money = integer cents)."""

    added_qty: int
    food_cost: int
    revenue: int  # incl. VAT, as rung up at the fridge
    revenue_ex_vat: int
    margin: int  # revenue_ex_vat - food_cost
    margin_pct: Decimal | None  # 0..1 fraction of ex-VAT revenue, 4 decimals


@dataclass(frozen=True)
class FridgeReportData:
    """Full fridge report: per-product rows plus the summary KPIs.

    Shared by the JSON endpoint and the Excel export so the numbers can never
    drift between the two surfaces (single source of truth).
    """

    fridge_id: int
    fridge_name: str
    date_from: datetime.date
    date_to: datetime.date
    rows: list[FridgeReportRowData]
    figures: ReportFigures


@dataclass(frozen=True)
class FridgeSummaryRowData:
    fridge_id: int
    fridge_name: str
    client_name: str
    figures: ReportFigures


@dataclass(frozen=True)
class AllFridgesReportData:
    """One summary row per fridge plus the totals, for JSON and Excel alike."""

    date_from: datetime.date
    date_to: datetime.date
    rows: list[FridgeSummaryRowData]
    totals: ReportFigures


def get_weekly_pnl(session: Session, year: int, iso_week: int) -> WeeklyPnlRead:
    window = _iso_week_window(year, iso_week)
    row = session.execute(
        select(WeeklyFinancial).where(
            WeeklyFinancial.year == year, WeeklyFinancial.iso_week == iso_week
        )
    ).scalar_one_or_none()

    inputs = WeeklyInputsRead(
        catering_turnover=row.catering_turnover if row else 0,
        catering_food_cost=row.catering_food_cost if row else 0,
        tgtg_turnover=row.tgtg_turnover if row else 0,
        logistics_cost=row.logistics_cost if row else 0,
        drops_count=row.drops_count if row else 0,
        unsold_items=row.unsold_items if row else 0,
        fridge_count=row.fridge_count if row else None,
        remarks=row.remarks if row else None,
    )

    sales_window = and_(
        SalesEvent.sold_at >= window.start, SalesEvent.sold_at < window.end
    )
    gross_sales = session.execute(
        select(func.coalesce(func.sum(SalesEvent.unit_price), 0)).where(sales_window)
    ).scalar_one()
    refunds = session.execute(
        select(func.coalesce(func.sum(SalesEvent.unit_price), 0)).where(
            sales_window, SalesEvent.is_refunded.is_(True)
        )
    ).scalar_one()
    customer_credit = session.execute(
        select(func.coalesce(func.sum(SalesEvent.discount_amount), 0)).where(
            sales_window, SalesEvent.discount_provider.is_(None)
        )
    ).scalar_one()
    frigoloco_discounts = session.execute(
        select(func.coalesce(func.sum(SalesEvent.discount_amount), 0)).where(
            sales_window, SalesEvent.discount_provider.is_not(None)
        )
    ).scalar_one()
    items_sold = session.execute(
        select(func.count()).select_from(SalesEvent).where(
            sales_window, SalesEvent.is_refunded.is_(False)
        )
    ).scalar_one()

    # ADDED-basis fridge food cost: valid ADDED events × product purchase price.
    fridge_food_cost = session.execute(
        select(func.coalesce(func.sum(Product.purchase_price), 0))
        .select_from(RestockEvent)
        .join(Product, Product.id == RestockEvent.product_id)
        .where(
            RestockEvent.occurred_at >= window.start,
            RestockEvent.occurred_at < window.end,
            RestockEvent.action == RestockAction.added,
            RestockEvent.tag_status == TagStatus.valid,
        )
    ).scalar_one()

    pos_fee_pct = (
        row.pos_fee_pct_snapshot
        if row
        else _read_setting_decimal(session, "pos_fee_pct", DEFAULT_POS_FEE_PCT)
    )
    rfid_fee_rate = (
        row.rfid_fee_snapshot
        if row
        else _read_setting_decimal(session, "rfid_fee_eur", DEFAULT_RFID_FEE_RATE)
    )

    gross_sales = Decimal(gross_sales)
    refunds = Decimal(refunds)
    customer_credit = Decimal(customer_credit)
    fridge_food_cost = Decimal(fridge_food_cost)

    turnover_ex_vat = (gross_sales + customer_credit - refunds) / VAT_DIVISOR
    pos_fee = gross_sales * Decimal(pos_fee_pct)
    rfid_fee = Decimal(rfid_fee_rate) * Decimal(items_sold)

    net_margin = (
        (turnover_ex_vat + inputs.catering_turnover + inputs.tgtg_turnover)
        - (fridge_food_cost + inputs.catering_food_cost + inputs.logistics_cost)
        - pos_fee
        - rfid_fee
    )
    now = datetime.datetime.now(LOCAL_TIMEZONE)

    return WeeklyPnlRead(
        year=year,
        iso_week=iso_week,
        week_start=window.start.date(),
        in_progress=window.start <= now < window.end,
        inputs=inputs,
        gross_sales=to_cents(gross_sales),
        refunds=to_cents(refunds),
        customer_credit=to_cents(customer_credit),
        frigoloco_discounts=to_cents(Decimal(frigoloco_discounts)),
        items_sold=int(items_sold),
        turnover_ex_vat=to_cents(turnover_ex_vat),
        fridge_food_cost_added=to_cents(fridge_food_cost),
        pos_fee_pct=pos_fee_pct,  # fraction (RateStr), not money
        rfid_fee_rate=to_cents(Decimal(rfid_fee_rate)),
        pos_fee=to_cents(pos_fee),
        rfid_fee=to_cents(rfid_fee),
        net_margin=to_cents(net_margin),
    )


def upsert_weekly_inputs(
    session: Session, year: int, iso_week: int, payload: WeeklyFinancialInputs
) -> WeeklyPnlRead:
    if not 1 <= iso_week <= 53:
        raise ApiError(422, "unprocessable_entity", "iso_week must be 1..53")

    row = session.execute(
        select(WeeklyFinancial).where(
            WeeklyFinancial.year == year, WeeklyFinancial.iso_week == iso_week
        )
    ).scalar_one_or_none()
    action = "update" if row else "create"
    if row is None:
        row = WeeklyFinancial(year=year, iso_week=iso_week)
        session.add(row)

    row.catering_turnover = payload.catering_turnover
    row.catering_food_cost = payload.catering_food_cost
    row.tgtg_turnover = payload.tgtg_turnover
    row.logistics_cost = payload.logistics_cost
    row.drops_count = payload.drops_count
    row.unsold_items = payload.unsold_items
    row.fridge_count = payload.fridge_count
    row.remarks = payload.remarks

    write_audit(
        session,
        action=action,
        entity="weekly_financial",
        entity_id=f"{year}-W{iso_week:02d}",
        after=payload.model_dump(mode="json"),
    )
    session.commit()
    return get_weekly_pnl(session, year, iso_week)


def get_monthly_analysis(
    session: Session, month: str, dimension: str
) -> MonthlyAnalysisRead:
    """Live P&L for one calendar month (Brussels days), grouped by ``dimension``."""
    year, month_number = _parse_month(month)
    window = _month_window(year, month_number)
    pos_fee_pct = _read_setting_decimal(session, "pos_fee_pct", DEFAULT_POS_FEE_PCT)
    rfid_rate = _read_setting_decimal(session, "rfid_fee_eur", DEFAULT_RFID_FEE_RATE)

    if dimension == "client":
        rows = _monthly_by_client(session, window, pos_fee_pct)
    elif dimension == "fridge":
        rows = _monthly_by_fridge(session, window, pos_fee_pct)
    elif dimension == "supplier":
        rows = _monthly_by_supplier(session, window, rfid_rate)
    elif dimension == "category":
        rows = _monthly_by_category(session, window, rfid_rate)
    else:
        raise ApiError(
            422,
            "unprocessable_entity",
            f"dimension must be one of {'|'.join(MONTHLY_DIMENSIONS)}",
        )

    return MonthlyAnalysisRead(month=month, dimension=dimension, rows=rows)


def build_fridge_report(
    session: Session,
    fridge_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
) -> FridgeReportData:
    """Compute the enriched fridge report (rows + summary) for a date window.

    Rows: each product ADDED (valid tags only) to the fridge in the window, with
    its added quantity and unit buying/selling prices (per-fridge selling-price
    override applied when present). Summary: see ``ReportFigures``.
    """
    # Select only the columns needed (not the whole ORM entity) so the report is
    # independent of any not-yet-migrated Fridge columns and avoids over-fetching.
    fridge_name = session.execute(
        select(Fridge.friendly_name).where(Fridge.id == fridge_id)
    ).scalar_one_or_none()
    if fridge_name is None:
        raise ApiError(404, "not_found", f"fridge {fridge_id} not found")
    window = _report_day_window(date_from, date_to)

    unit_selling = func.coalesce(FridgeProductPrice.sales_price, Product.sales_price)
    row_records = session.execute(
        select(
            Product.id,
            Product.code,
            Product.name,
            Category.name,
            func.count().label("added_qty"),
            Product.purchase_price,
            unit_selling.label("unit_selling_price"),
        )
        .select_from(RestockEvent)
        .join(Product, Product.id == RestockEvent.product_id)
        .join(Category, Category.id == Product.category_id)
        .outerjoin(
            FridgeProductPrice,
            and_(
                FridgeProductPrice.product_id == Product.id,
                FridgeProductPrice.fridge_id == fridge_id,
            ),
        )
        .where(
            RestockEvent.fridge_id == fridge_id,
            _valid_added_in_window(window),
        )
        .group_by(
            Product.id,
            Product.code,
            Product.name,
            Category.name,
            Product.purchase_price,
            unit_selling,
        )
        .order_by(func.count().desc(), Product.name)
    ).all()

    rows: list[FridgeReportRowData] = []
    total_added_qty = 0
    food_cost = 0
    for product_id, code, name, category, added_qty, buying, selling in row_records:
        added_qty = int(added_qty)
        total_added_qty += added_qty
        food_cost += added_qty * int(buying)
        rows.append(
            FridgeReportRowData(
                product_id=product_id,
                code=code,
                name=name,
                category=category,
                added_qty=added_qty,
                unit_buying_price=int(buying),
                unit_selling_price=int(selling),
            )
        )

    revenue = session.execute(
        select(func.coalesce(func.sum(SalesEvent.unit_price), 0)).where(
            SalesEvent.fridge_id == fridge_id,
            _unrefunded_sales_in_window(window),
        )
    ).scalar_one()

    return FridgeReportData(
        fridge_id=fridge_id,
        fridge_name=fridge_name,
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        figures=_build_report_figures(
            added_qty=total_added_qty,
            food_cost=food_cost,
            revenue=int(revenue),
        ),
    )


def get_fridge_gsv_report(
    session: Session,
    fridge_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
) -> FridgeReportRead:
    """JSON view of the fridge report (per-product rows + summary KPIs)."""
    data = build_fridge_report(session, fridge_id, date_from, date_to)
    figures = data.figures
    return FridgeReportRead(
        fridge_id=data.fridge_id,
        date_from=data.date_from,
        date_to=data.date_to,
        added_qty=figures.added_qty,
        food_cost=figures.food_cost,
        revenue=figures.revenue,
        revenue_ex_vat=figures.revenue_ex_vat,
        margin=figures.margin,
        margin_pct=figures.margin_pct,
        rows=[
            FridgeReportRow(
                product_id=row.product_id,
                code=row.code,
                name=row.name,
                category=row.category,
                added_qty=row.added_qty,
                unit_buying_price=row.unit_buying_price,
                unit_selling_price=row.unit_selling_price,
            )
            for row in data.rows
        ],
    )


def build_all_fridges_report(
    session: Session,
    date_from: datetime.date,
    date_to: datetime.date,
) -> AllFridgesReportData:
    """Fridge-report KPIs for every fridge over a date window, plus the totals.

    Lists every active fridge (even without activity) and any inactive fridge that
    still had restocks or sales in the window.
    """
    window = _report_day_window(date_from, date_to)
    added_records = session.execute(
        select(
            RestockEvent.fridge_id,
            func.count(),
            func.sum(Product.purchase_price),
        )
        .join(Product, Product.id == RestockEvent.product_id)
        .where(_valid_added_in_window(window))
        .group_by(RestockEvent.fridge_id)
    ).all()
    added_by_fridge = {
        fridge_id: (int(added_qty), int(food_cost))
        for fridge_id, added_qty, food_cost in added_records
    }
    revenue_by_fridge = dict(
        session.execute(
            select(SalesEvent.fridge_id, func.sum(SalesEvent.unit_price))
            .where(_unrefunded_sales_in_window(window))
            .group_by(SalesEvent.fridge_id)
        ).all()
    )
    client_names = dict(session.execute(select(Client.id, Client.name)).all())

    rows: list[FridgeSummaryRowData] = []
    fridge_refs = _load_fridge_refs(session)
    for fridge in fridge_refs:
        has_activity = fridge.fridge_id in added_by_fridge or fridge.fridge_id in revenue_by_fridge
        if not fridge.is_active and not has_activity:
            continue
        added_qty, food_cost = added_by_fridge.get(fridge.fridge_id, (0, 0))
        rows.append(
            FridgeSummaryRowData(
                fridge_id=fridge.fridge_id,
                fridge_name=fridge.name,
                client_name=_client_name(client_names, fridge.client_id),
                figures=_build_report_figures(
                    added_qty=added_qty,
                    food_cost=food_cost,
                    revenue=int(revenue_by_fridge.get(fridge.fridge_id, 0)),
                ),
            )
        )

    return AllFridgesReportData(
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        totals=_sum_report_figures([row.figures for row in rows]),
    )


def get_all_fridges_report(
    session: Session,
    date_from: datetime.date,
    date_to: datetime.date,
) -> AllFridgesReportRead:
    """JSON view of the all-fridges report."""
    data = build_all_fridges_report(session, date_from, date_to)
    return AllFridgesReportRead(
        date_from=data.date_from,
        date_to=data.date_to,
        rows=[
            _build_all_fridges_row(
                fridge_id=row.fridge_id,
                fridge_name=row.fridge_name,
                client_name=row.client_name,
                figures=row.figures,
            )
            for row in data.rows
        ],
        totals=_build_all_fridges_row(
            fridge_id=None,
            fridge_name=TOTAL_ROW_NAME,
            client_name=None,
            figures=data.totals,
        ),
    )


def _read_setting_decimal(session: Session, key: str, default: Decimal) -> Decimal:
    row = session.get(Setting, key)
    if row is None or row.value is None:
        return default
    try:
        return Decimal(str(row.value))
    except (ValueError, ArithmeticError):
        return default


def _local_midnight(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=LOCAL_TIMEZONE)


def _iso_week_window(year: int, iso_week: int) -> DateWindow:
    try:
        monday = datetime.date.fromisocalendar(year, iso_week, 1)
    except ValueError as exc:
        raise ApiError(422, "unprocessable_entity", str(exc)) from exc
    next_monday = monday + datetime.timedelta(days=DAYS_PER_WEEK)
    return DateWindow(start=_local_midnight(monday), end=_local_midnight(next_monday))


def _month_window(year: int, month: int) -> DateWindow:
    first_day = datetime.date(year, month, 1)
    if month == 12:
        next_month_first_day = datetime.date(year + 1, 1, 1)
    else:
        next_month_first_day = datetime.date(year, month + 1, 1)
    return DateWindow(
        start=_local_midnight(first_day),
        end=_local_midnight(next_month_first_day),
    )


def _report_day_window(date_from: datetime.date, date_to: datetime.date) -> DateWindow:
    """Inclusive ``date_from``..``date_to`` as a half-open Brussels-time window."""
    if date_to < date_from:
        raise ApiError(422, "unprocessable_entity", "date_to cannot precede date_from")
    day_after_end = date_to + datetime.timedelta(days=1)
    return DateWindow(start=_local_midnight(date_from), end=_local_midnight(day_after_end))


def _valid_added_in_window(window: DateWindow):
    return and_(
        RestockEvent.occurred_at >= window.start,
        RestockEvent.occurred_at < window.end,
        RestockEvent.action == RestockAction.added,
        RestockEvent.tag_status == TagStatus.valid,
    )


def _unrefunded_sales_in_window(window: DateWindow):
    return and_(
        SalesEvent.sold_at >= window.start,
        SalesEvent.sold_at < window.end,
        SalesEvent.is_refunded.is_(False),
    )


def _build_report_figures(*, added_qty: int, food_cost: int, revenue: int) -> ReportFigures:
    revenue_ex_vat = to_cents(Decimal(revenue) / VAT_DIVISOR)
    margin = revenue_ex_vat - food_cost
    return ReportFigures(
        added_qty=added_qty,
        food_cost=food_cost,
        revenue=revenue,
        revenue_ex_vat=revenue_ex_vat,
        margin=margin,
        margin_pct=_margin_fraction(margin, revenue_ex_vat),
    )


def _sum_report_figures(figures_list: list[ReportFigures]) -> ReportFigures:
    """Totals add the rounded row cents, so the total row equals the column sums."""
    revenue_ex_vat = sum(figures.revenue_ex_vat for figures in figures_list)
    margin = sum(figures.margin for figures in figures_list)
    return ReportFigures(
        added_qty=sum(figures.added_qty for figures in figures_list),
        food_cost=sum(figures.food_cost for figures in figures_list),
        revenue=sum(figures.revenue for figures in figures_list),
        revenue_ex_vat=revenue_ex_vat,
        margin=margin,
        margin_pct=_margin_fraction(margin, revenue_ex_vat),
    )


def _margin_fraction(margin: int, revenue_ex_vat: int) -> Decimal | None:
    if revenue_ex_vat <= 0:
        return None
    return (Decimal(margin) / Decimal(revenue_ex_vat)).quantize(_FOUR_PLACES)


def _build_all_fridges_row(
    *,
    fridge_id: int | None,
    fridge_name: str,
    client_name: str | None,
    figures: ReportFigures,
) -> AllFridgesReportRow:
    return AllFridgesReportRow(
        fridge_id=fridge_id,
        fridge_name=fridge_name,
        client_name=client_name,
        added_qty=figures.added_qty,
        food_cost=figures.food_cost,
        revenue=figures.revenue,
        revenue_ex_vat=figures.revenue_ex_vat,
        margin=figures.margin,
        margin_pct=figures.margin_pct,
    )


def _parse_month(month: str) -> tuple[int, int]:
    try:
        parsed = datetime.datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ApiError(
            422, "unprocessable_entity", "month must be formatted YYYY-MM"
        ) from exc
    return parsed.year, parsed.month


def _client_name(client_names: dict[int, str], client_id: int | None) -> str:
    if client_id is None:
        return NO_CLIENT_NAME
    return client_names.get(client_id, f"client {client_id}")


def _load_fridge_refs(session: Session) -> list[_FridgeRef]:
    """Every fridge; active = Husky-active with no local inactive/cancelled override."""
    is_active = and_(Fridge.is_active.is_(True), Fridge.local_status.is_(None))
    records = session.execute(
        select(
            Fridge.id,
            Fridge.friendly_name,
            Fridge.client_id,
            is_active.label("is_active"),
        ).order_by(Fridge.friendly_name)
    ).all()
    return [
        _FridgeRef(
            fridge_id=record.id,
            name=record.friendly_name,
            client_id=record.client_id,
            is_active=record.is_active,
        )
        for record in records
    ]


def _dispatched_food_margin(session: Session, window: DateWindow, group_key):
    """Sum of qty x (sales_ex_vat - purchase) per ``group_key`` over the month's
    dispatched/reconciled dispatches (by delivery date)."""
    unit_sales_ex_vat = func.coalesce(
        DispatchLine.unit_sales_price, Product.sales_price
    ) / (1 + func.coalesce(DispatchLine.vat_rate, Product.vat_rate))
    unit_purchase = func.coalesce(DispatchLine.unit_purchase_price, Product.purchase_price)
    margin_expr = func.sum(DispatchLine.qty * (unit_sales_ex_vat - unit_purchase))
    rows = session.execute(
        select(group_key, margin_expr)
        .select_from(DispatchLine)
        .join(Product, Product.id == DispatchLine.product_id)
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .join(Fridge, Fridge.id == DispatchLine.fridge_id)
        .where(
            Dispatch.delivery_date >= window.start.date(),
            Dispatch.delivery_date < window.end.date(),
            Dispatch.status.in_(MARGIN_DISPATCH_STATUSES),
        )
        .group_by(group_key)
    ).all()
    return {key: Decimal(value or 0) for key, value in rows}


def _sales_and_items(
    session: Session,
    window: DateWindow,
    group_key,
) -> dict[int | None, _SalesTotals]:
    rows = session.execute(
        select(
            group_key,
            func.coalesce(func.sum(SalesEvent.unit_price), 0),
            func.count(),
        )
        .select_from(SalesEvent)
        .join(Fridge, Fridge.id == SalesEvent.fridge_id)
        .join(Product, Product.id == SalesEvent.product_id)
        .where(_unrefunded_sales_in_window(window))
        .group_by(group_key)
    ).all()
    return {
        key: _SalesTotals(sales=Decimal(total), items=int(count))
        for key, total, count in rows
    }


def _prorated_month_logistics(session: Session, window: DateWindow) -> Decimal:
    """Weekly logistics of the weeks overlapping the month, each prorated by the
    number of its days that fall inside the month."""
    month_days_by_week = _month_days_per_iso_week(window)
    weekly_costs = session.execute(
        select(
            WeeklyFinancial.year,
            WeeklyFinancial.iso_week,
            WeeklyFinancial.logistics_cost,
        ).where(
            tuple_(WeeklyFinancial.year, WeeklyFinancial.iso_week).in_(
                list(month_days_by_week)
            )
        )
    ).all()
    logistics_total = ZERO
    for year, iso_week, logistics_cost in weekly_costs:
        days_in_month = month_days_by_week[(year, iso_week)]
        logistics_total += Decimal(logistics_cost) * days_in_month / DAYS_PER_WEEK
    return logistics_total


def _month_days_per_iso_week(window: DateWindow) -> dict[tuple[int, int], int]:
    """(iso_year, iso_week) -> how many days of that week lie inside the month."""
    days_by_week: Counter[tuple[int, int]] = Counter()
    day = window.start.date()
    month_end = window.end.date()
    while day < month_end:
        iso_date = day.isocalendar()
        days_by_week[(iso_date.year, iso_date.week)] += 1
        day += datetime.timedelta(days=1)
    return dict(days_by_week)


def _load_client_month_costs(session: Session, window: DateWindow) -> _ClientMonthCosts:
    month_first_day = window.start.date()
    fee_rows = session.execute(
        select(ClientFee.client_id, func.sum(ClientFee.yearly_fee)).where(
            ClientFee.contract_start <= month_first_day,
            (ClientFee.contract_end.is_(None))
            | (ClientFee.contract_end >= month_first_day),
        ).group_by(ClientFee.client_id)
    ).all()
    service_rows = session.execute(
        select(ClientServiceCharge.client_id, func.sum(ClientServiceCharge.amount))
        .where(ClientServiceCharge.month == month_first_day)
        .group_by(ClientServiceCharge.client_id)
    ).all()

    fridges = _load_fridge_refs(session)
    active_fridge_count = sum(1 for fridge in fridges if fridge.is_active)
    logistics_total = _prorated_month_logistics(session, window)
    logistics_per_active_fridge = (
        logistics_total / active_fridge_count if active_fridge_count else ZERO
    )
    return _ClientMonthCosts(
        fee_share_by_client={
            client_id: Decimal(yearly_fee) / MONTHS_PER_YEAR
            for client_id, yearly_fee in fee_rows
        },
        service_by_client={
            client_id: Decimal(amount) for client_id, amount in service_rows
        },
        logistics_per_active_fridge=logistics_per_active_fridge,
        client_names=dict(session.execute(select(Client.id, Client.name)).all()),
        fridges=fridges,
    )


def _monthly_by_client(
    session: Session, window: DateWindow, pos_fee_pct: Decimal
) -> list[MonthlyAnalysisRow]:
    """One row per client; fridges without a client are grouped under "No client".
    Logistics is split equally over all active fridges."""
    costs = _load_client_month_costs(session, window)
    margin_by_client = _dispatched_food_margin(session, window, Fridge.client_id)
    sales_by_client = _sales_and_items(session, window, Fridge.client_id)
    active_fridges_by_client = Counter(
        fridge.client_id for fridge in costs.fridges if fridge.is_active
    )
    client_ids = (
        set(margin_by_client)
        | set(sales_by_client)
        | set(costs.fee_share_by_client)
        | set(costs.service_by_client)
        | set(active_fridges_by_client)
    )

    rows: list[MonthlyAnalysisRow] = []
    for client_id in client_ids:
        active_fridge_count = active_fridges_by_client.get(client_id, 0)
        amounts = _ClientCostAmounts(
            sales=sales_by_client.get(client_id, _NO_SALES).sales,
            food_margin=margin_by_client.get(client_id, ZERO),
            fee_share=costs.fee_share_by_client.get(client_id, ZERO),
            service_additionals=costs.service_by_client.get(client_id, ZERO),
            logistics_share=costs.logistics_per_active_fridge * active_fridge_count,
        )
        label = _MonthlyRowLabel(
            key_id=client_id,
            key_name=_client_name(costs.client_names, client_id),
            client_name=None,
            fridge_count=active_fridge_count,
        )
        rows.append(_build_client_cost_row(label, amounts, pos_fee_pct))
    return sorted(rows, key=_monthly_row_sort_key)


def _monthly_by_fridge(
    session: Session, window: DateWindow, pos_fee_pct: Decimal
) -> list[MonthlyAnalysisRow]:
    """One row per fridge. Client fee and service charges are split equally over the
    client's active fridges; logistics equally over all active fridges. A client with
    charges but no active fridge keeps them on its own "(no active fridge)" row so the
    totals match the client view."""
    costs = _load_client_month_costs(session, window)
    margin_by_fridge = _dispatched_food_margin(session, window, DispatchLine.fridge_id)
    sales_by_fridge = _sales_and_items(session, window, SalesEvent.fridge_id)
    active_fridges_by_client = Counter(
        fridge.client_id for fridge in costs.fridges if fridge.is_active
    )

    rows: list[MonthlyAnalysisRow] = []
    for fridge in costs.fridges:
        has_activity = fridge.fridge_id in margin_by_fridge or fridge.fridge_id in sales_by_fridge
        if not fridge.is_active and not has_activity:
            continue
        client_share = ZERO
        if fridge.is_active and fridge.client_id is not None:
            client_share = 1 / Decimal(active_fridges_by_client[fridge.client_id])
        logistics_share = costs.logistics_per_active_fridge if fridge.is_active else ZERO
        amounts = _ClientCostAmounts(
            sales=sales_by_fridge.get(fridge.fridge_id, _NO_SALES).sales,
            food_margin=margin_by_fridge.get(fridge.fridge_id, ZERO),
            fee_share=costs.fee_share_by_client.get(fridge.client_id, ZERO) * client_share,
            service_additionals=(
                costs.service_by_client.get(fridge.client_id, ZERO) * client_share
            ),
            logistics_share=logistics_share,
        )
        label = _MonthlyRowLabel(
            key_id=fridge.fridge_id,
            key_name=fridge.name,
            client_name=_client_name(costs.client_names, fridge.client_id),
            fridge_count=None,
        )
        rows.append(_build_client_cost_row(label, amounts, pos_fee_pct))

    charged_client_ids = set(costs.fee_share_by_client) | set(costs.service_by_client)
    for client_id in charged_client_ids:
        if active_fridges_by_client.get(client_id, 0) > 0:
            continue
        client_name = _client_name(costs.client_names, client_id)
        amounts = _ClientCostAmounts(
            sales=ZERO,
            food_margin=ZERO,
            fee_share=costs.fee_share_by_client.get(client_id, ZERO),
            service_additionals=costs.service_by_client.get(client_id, ZERO),
            logistics_share=ZERO,
        )
        label = _MonthlyRowLabel(
            key_id=None,
            key_name=f"{client_name} {NO_ACTIVE_FRIDGE_SUFFIX}",
            client_name=client_name,
            fridge_count=None,
        )
        rows.append(_build_client_cost_row(label, amounts, pos_fee_pct))
    return sorted(rows, key=_monthly_row_sort_key)


def _build_client_cost_row(
    label: _MonthlyRowLabel,
    amounts: _ClientCostAmounts,
    pos_fee_pct: Decimal,
) -> MonthlyAnalysisRow:
    pos_fee = amounts.sales * pos_fee_pct
    net_margin = (
        amounts.fee_share
        + amounts.food_margin
        + amounts.service_additionals
        - amounts.logistics_share
        - pos_fee
    )
    return MonthlyAnalysisRow(
        key_id=label.key_id,
        key_name=label.key_name,
        client_name=label.client_name,
        fridge_count=label.fridge_count,
        food_margin=to_cents(amounts.food_margin),
        sales=to_cents(amounts.sales),
        sales_ex_vat=to_cents(amounts.sales / VAT_DIVISOR),
        pos_fee=to_cents(pos_fee),
        fee_share=to_cents(amounts.fee_share),
        service_additionals=to_cents(amounts.service_additionals),
        logistics_share=to_cents(amounts.logistics_share),
        net_margin=to_cents(net_margin),
    )


def _monthly_row_sort_key(row: MonthlyAnalysisRow) -> tuple[bool, str]:
    """Alphabetical, with the "No client" catch-all last."""
    return (row.key_name == NO_CLIENT_NAME, row.key_name.lower())


def _monthly_by_supplier(
    session: Session, window: DateWindow, rfid_rate: Decimal
) -> list[MonthlyAnalysisRow]:
    margin_by = _dispatched_food_margin(session, window, Product.supplier_id)
    sales_by = _sales_and_items(session, window, Product.supplier_id)
    names = dict(session.execute(select(Supplier.id, Supplier.name)).all())
    return _build_margin_minus_rfid_rows(margin_by, sales_by, rfid_rate, names)


def _monthly_by_category(
    session: Session, window: DateWindow, rfid_rate: Decimal
) -> list[MonthlyAnalysisRow]:
    margin_by = _dispatched_food_margin(session, window, Product.category_id)
    sales_by = _sales_and_items(session, window, Product.category_id)
    names = dict(session.execute(select(Category.id, Category.name)).all())
    return _build_margin_minus_rfid_rows(margin_by, sales_by, rfid_rate, names)


def _build_margin_minus_rfid_rows(
    margin_by: dict,
    sales_by: dict[int | None, _SalesTotals],
    rfid_rate: Decimal,
    names: dict,
) -> list[MonthlyAnalysisRow]:
    keys = set(margin_by) | set(sales_by)
    keys.discard(None)
    rows: list[MonthlyAnalysisRow] = []
    for key in sorted(keys):
        food_margin = margin_by.get(key, ZERO)
        rfid_fee = rfid_rate * Decimal(sales_by.get(key, _NO_SALES).items)
        rows.append(
            MonthlyAnalysisRow(
                key_id=key,
                key_name=names.get(key, str(key)),
                food_margin=to_cents(food_margin),
                rfid_fee=to_cents(rfid_fee),
                net_margin=to_cents(food_margin - rfid_fee),
            )
        )
    return rows



_DEFAULT_SCORECARD_SORT_FIELD = "final_score"


@dataclass(frozen=True)
class ScorecardFilters:
    category_id: int | None
    supplier_id: int | None
    search: str | None


@dataclass(frozen=True)
class ScorecardRowData:
    """One stored product score plus the product's current catalogue facts (money = cents)."""

    product_id: int
    name: str
    code: str
    category: str | None
    supplier_name: str | None
    shelf_life_days: int | None
    buying_price: int
    sold_price: int
    vat_rate: Decimal
    profit_margin: Decimal | None
    total_sold_qty: int | None
    total_added_qty: int
    pct_sold: Decimal | None
    positive_reviews: int | None
    negative_reviews: int | None
    pct_positive_review: Decimal | None
    final_score: Decimal
    uses_new_product_baseline: bool


@dataclass(frozen=True)
class ScorecardResult:
    rows: list[ScorecardRowData]
    total: int
    weights: scoring_service.ScoringWeights
    window_days: int
    period_end: datetime.date | None
    computed_at: datetime.datetime | None


_SCORECARD_SORT_KEYS: dict[str, callable] = {
    "final_score": lambda row: row.final_score,
    "name": lambda row: row.name.lower(),
    "code": lambda row: row.code.lower(),
    "category": lambda row: (row.category or "").lower(),
    "supplier": lambda row: (row.supplier_name or "").lower(),
    "buying_price": lambda row: row.buying_price,
    "sold_price": lambda row: row.sold_price,
    "vat_rate": lambda row: row.vat_rate,
    "profit_margin": lambda row: row.profit_margin,
    "total_sold_qty": lambda row: row.total_sold_qty,
    "total_added_qty": lambda row: row.total_added_qty,
    "pct_sold": lambda row: row.pct_sold,
    "positive_reviews": lambda row: row.positive_reviews,
    "negative_reviews": lambda row: row.negative_reviews,
    "pct_positive_review": lambda row: row.pct_positive_review,
    "shelf_life_days": lambda row: row.shelf_life_days,
}


@dataclass(frozen=True)
class _SortSpec:
    field: str
    descending: bool


def build_scorecard(
    session: Session,
    *,
    window_days: int,
    filters: ScorecardFilters,
    limit: int,
    offset: int,
    sort: str | None,
) -> ScorecardResult:
    """Stored ``product_scores`` of the newest period for ``window_days``, filtered,
    sorted server-side, then paginated. Empty with ``period_end=None`` when that
    window was never computed."""
    sort_spec = _parse_scorecard_sort(sort)
    weights = scoring_service.load_weights(session)
    period_end = scoring_service.latest_score_period(session, window_days)
    if period_end is None:
        return ScorecardResult(
            rows=[],
            total=0,
            weights=weights,
            window_days=window_days,
            period_end=None,
            computed_at=None,
        )

    computed_at = session.execute(
        select(func.max(ProductScore.computed_at)).where(
            ProductScore.window_days == window_days,
            ProductScore.period_end == period_end,
        )
    ).scalar_one()
    score_records = session.execute(
        _stored_scores_query(window_days, period_end, filters)
    ).all()
    rows = [_build_scorecard_row(record) for record in score_records]
    sorted_rows = _sort_scorecard_rows(rows, sort_spec)
    return ScorecardResult(
        rows=sorted_rows[offset : offset + limit],
        total=len(sorted_rows),
        weights=weights,
        window_days=window_days,
        period_end=period_end,
        computed_at=computed_at,
    )


def _parse_scorecard_sort(sort: str | None) -> _SortSpec:
    """Parse ``?sort=<field> [asc|desc]`` into a validated sort spec.

    Default: ``final_score desc``. Unknown fields raise a 422.
    """
    if not sort or not sort.strip():
        return _SortSpec(field=_DEFAULT_SCORECARD_SORT_FIELD, descending=True)
    parts = sort.replace(":", " ").split()
    field = parts[0]
    if field not in _SCORECARD_SORT_KEYS:
        raise ApiError(
            422,
            "unprocessable_entity",
            f"sort field must be one of {sorted(_SCORECARD_SORT_KEYS)}",
        )
    if len(parts) > 1:
        direction = parts[1].lower()
        if direction not in ("asc", "desc"):
            raise ApiError(
                422, "unprocessable_entity", "sort direction must be asc or desc"
            )
        descending = direction == "desc"
    else:
        descending = field == _DEFAULT_SCORECARD_SORT_FIELD
    return _SortSpec(field=field, descending=descending)


def _stored_scores_query(
    window_days: int,
    period_end: datetime.date,
    filters: ScorecardFilters,
):
    conditions = [
        ProductScore.window_days == window_days,
        ProductScore.period_end == period_end,
    ]
    if filters.category_id is not None:
        conditions.append(Product.category_id == filters.category_id)
    if filters.supplier_id is not None:
        conditions.append(Product.supplier_id == filters.supplier_id)
    if filters.search:
        search_pattern = f"%{filters.search}%"
        conditions.append(
            or_(
                Product.code.ilike(search_pattern),
                Product.name.ilike(search_pattern),
            )
        )
    return (
        select(
            ProductScore,
            Product.code,
            Product.name,
            Product.shelf_life_days,
            Product.purchase_price,
            Product.sales_price,
            Product.vat_rate,
            Category.name.label("category_name"),
            Supplier.name.label("supplier_name"),
        )
        .join(Product, Product.id == ProductScore.product_id)
        .outerjoin(Category, Category.id == Product.category_id)
        .outerjoin(Supplier, Supplier.id == Product.supplier_id)
        .where(*conditions)
        .order_by(Product.name)
    )


def _build_scorecard_row(record) -> ScorecardRowData:
    score: ProductScore = record.ProductScore
    pct_positive = _positive_review_share(score.positive_reviews, score.negative_reviews)
    return ScorecardRowData(
        product_id=score.product_id,
        name=record.name,
        code=record.code,
        category=record.category_name,
        supplier_name=record.supplier_name,
        shelf_life_days=record.shelf_life_days,
        buying_price=int(record.purchase_price),
        sold_price=int(record.sales_price),
        vat_rate=record.vat_rate,
        profit_margin=score.margin_score,
        total_sold_qty=score.sold_qty,
        total_added_qty=score.sample_size,
        pct_sold=score.pct_sold,
        positive_reviews=score.positive_reviews,
        negative_reviews=score.negative_reviews,
        pct_positive_review=pct_positive,
        final_score=score.final_score,
        uses_new_product_baseline=score.uses_new_product_baseline,
    )


def _positive_review_share(
    positive_reviews: int | None,
    negative_reviews: int | None,
) -> Decimal | None:
    """Positive / all reviews; None for rows stored before review counts were kept."""
    if positive_reviews is None or negative_reviews is None:
        return None
    total_reviews = positive_reviews + negative_reviews
    if total_reviews == 0:
        return None
    share = Decimal(positive_reviews) / Decimal(total_reviews)
    return share.quantize(_FOUR_PLACES)


def _sort_scorecard_rows(
    rows: list[ScorecardRowData],
    sort_spec: _SortSpec,
) -> list[ScorecardRowData]:
    sort_key = _SCORECARD_SORT_KEYS[sort_spec.field]
    # Missing (None) values always sort last, independent of direction.
    rows_with_value = [row for row in rows if sort_key(row) is not None]
    rows_without_value = [row for row in rows if sort_key(row) is None]
    rows_with_value.sort(key=sort_key, reverse=sort_spec.descending)
    return rows_with_value + rows_without_value
