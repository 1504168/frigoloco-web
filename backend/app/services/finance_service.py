"""Finance domain logic (R10/R11/R12): weekly P&L, live monthly analysis by
client/supplier/category, and per-fridge GSV reports.

Verified formulas (IMPLEMENTATION-BRIEF): sales turnover ex-VAT =
``(gross + credit − refunds) / 1.06``; POS fee = 9% of VAT-INCLUSIVE gross;
RFID fee = rate × items_sold; weekly food cost uses the ADDED (restock) basis;
monthly food margin uses the DISPATCHED basis.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import RestockAction, TagStatus
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
from app.schemas.finance import (
    FridgeReportRead,
    FridgeReportRow,
    MonthlyAnalysisRead,
    MonthlyAnalysisRow,
    WeeklyFinancialInputs,
    WeeklyInputsRead,
    WeeklyPnlRead,
)
from app.money import to_cents
from app.services import scoring_service
from app.services.orders_service import ApiError, write_audit

VAT_DIVISOR = Decimal("1.06")
DEFAULT_POS_FEE_PCT = Decimal("0.09")  # fraction (NOT money)
# RFID fee is money in cents now: EUR 0.10 -> 10 cents per item sold.
DEFAULT_RFID_FEE_RATE = Decimal("10")

# Every ratio the service emits (margin, %sold, review, scores) is a plain 0..1
# fraction quantized to four decimal places.
_FOUR_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class DateWindow:
    start: datetime.datetime
    end: datetime.datetime


def _read_setting_decimal(session: Session, key: str, default: Decimal) -> Decimal:
    row = session.get(Setting, key)
    if row is None or row.value is None:
        return default
    try:
        return Decimal(str(row.value))
    except (ValueError, ArithmeticError):
        return default


def _iso_week_window(year: int, iso_week: int) -> DateWindow:
    try:
        monday = datetime.date.fromisocalendar(year, iso_week, 1)
    except ValueError as exc:
        raise ApiError(422, "unprocessable_entity", str(exc)) from exc
    start = datetime.datetime.combine(monday, datetime.time.min, tzinfo=datetime.timezone.utc)
    return DateWindow(start=start, end=start + datetime.timedelta(days=7))


def _month_window(year: int, month: int) -> DateWindow:
    first = datetime.date(year, month, 1)
    if month == 12:
        nxt = datetime.date(year + 1, 1, 1)
    else:
        nxt = datetime.date(year, month + 1, 1)
    start = datetime.datetime.combine(first, datetime.time.min, tzinfo=datetime.timezone.utc)
    end = datetime.datetime.combine(nxt, datetime.time.min, tzinfo=datetime.timezone.utc)
    return DateWindow(start=start, end=end)


def _sales_ex_vat_expr():
    """dispatch line ex-VAT unit sales price, snapshot-first, product fallback."""
    unit_sales = func.coalesce(DispatchLine.unit_sales_price, Product.sales_price)
    vat = func.coalesce(DispatchLine.vat_rate, Product.vat_rate)
    return unit_sales / (1 + vat)


def _purchase_price_expr():
    return func.coalesce(DispatchLine.unit_purchase_price, Product.purchase_price)


# ===========================================================================
# Weekly P&L (R10)
# ===========================================================================


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

    return WeeklyPnlRead(
        year=year,
        iso_week=iso_week,
        week_start=window.start.date(),
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


# ===========================================================================
# Monthly analysis (R11/R12) - live aggregation, no stored table
# ===========================================================================


def _parse_month(month: str) -> tuple[int, int]:
    try:
        parsed = datetime.datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ApiError(
            422, "unprocessable_entity", "month must be formatted YYYY-MM"
        ) from exc
    return parsed.year, parsed.month


def _dispatched_food_margin(session: Session, window: DateWindow, group_key):
    """Σ qty × (sales_ex_vat − purchase) grouped by ``group_key`` for the month.

    The dispatch month is taken from the dispatch line's delivery via the join to
    ``dispatches``; here we approximate by the ``DispatchLine`` rows whose parent
    dispatch delivery_date falls in the window.
    """
    margin_expr = func.sum(
        DispatchLine.qty * (_sales_ex_vat_expr() - _purchase_price_expr())
    )
    rows = session.execute(
        select(group_key, margin_expr)
        .select_from(DispatchLine)
        .join(Product, Product.id == DispatchLine.product_id)
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .where(
            Dispatch.delivery_date >= window.start.date(),
            Dispatch.delivery_date < window.end.date(),
        )
        .group_by(group_key)
    ).all()
    return {key: Decimal(value or 0) for key, value in rows}


def _sales_and_items(session: Session, window: DateWindow, group_key):
    sales_window = and_(
        SalesEvent.sold_at >= window.start, SalesEvent.sold_at < window.end
    )
    rows = session.execute(
        select(
            group_key,
            func.coalesce(func.sum(SalesEvent.unit_price), 0),
            func.count(),
        )
        .select_from(SalesEvent)
        .join(Product, Product.id == SalesEvent.product_id)
        .where(sales_window, SalesEvent.is_refunded.is_(False))
        .group_by(group_key)
    ).all()
    return {key: (Decimal(total or 0), int(count)) for key, total, count in rows}


def _client_sales_and_items(session: Session, window: DateWindow):
    sales_window = and_(
        SalesEvent.sold_at >= window.start, SalesEvent.sold_at < window.end
    )
    rows = session.execute(
        select(
            Fridge.client_id,
            func.coalesce(func.sum(SalesEvent.unit_price), 0),
            func.count(),
        )
        .select_from(SalesEvent)
        .join(Fridge, Fridge.id == SalesEvent.fridge_id)
        .where(sales_window, SalesEvent.is_refunded.is_(False))
        .group_by(Fridge.client_id)
    ).all()
    return {key: (Decimal(total or 0), int(count)) for key, total, count in rows}


def get_monthly_analysis(
    session: Session, month: str, dimension: str
) -> MonthlyAnalysisRead:
    year, mon = _parse_month(month)
    window = _month_window(year, mon)
    pos_fee_pct = _read_setting_decimal(session, "pos_fee_pct", DEFAULT_POS_FEE_PCT)
    rfid_rate = _read_setting_decimal(session, "rfid_fee_eur", DEFAULT_RFID_FEE_RATE)

    if dimension == "client":
        rows = _monthly_by_client(session, window, mon, pos_fee_pct)
    elif dimension == "supplier":
        rows = _monthly_by_supplier(session, window, rfid_rate)
    elif dimension == "category":
        rows = _monthly_by_category(session, window, rfid_rate)
    else:
        raise ApiError(
            422, "unprocessable_entity", "dimension must be client|supplier|category"
        )

    return MonthlyAnalysisRead(month=month, dimension=dimension, rows=rows)


def _monthly_by_client(
    session: Session, window: DateWindow, mon: int, pos_fee_pct: Decimal
) -> list[MonthlyAnalysisRow]:
    # food margin per client (dispatched basis) via client → fridge → dispatch line.
    margin_expr = func.sum(
        DispatchLine.qty * (_sales_ex_vat_expr() - _purchase_price_expr())
    )
    margin_rows = session.execute(
        select(Fridge.client_id, margin_expr)
        .select_from(DispatchLine)
        .join(Product, Product.id == DispatchLine.product_id)
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .join(Fridge, Fridge.id == DispatchLine.fridge_id)
        .where(
            Dispatch.delivery_date >= window.start.date(),
            Dispatch.delivery_date < window.end.date(),
        )
        .group_by(Fridge.client_id)
    ).all()
    margin_by_client = {cid: Decimal(v or 0) for cid, v in margin_rows}

    sales_by_client = _client_sales_and_items(session, window)

    month_first = window.start.date()
    fee_rows = session.execute(
        select(ClientFee.client_id, func.sum(ClientFee.yearly_fee)).where(
            ClientFee.contract_start <= month_first,
            (ClientFee.contract_end.is_(None))
            | (ClientFee.contract_end >= month_first),
        ).group_by(ClientFee.client_id)
    ).all()
    fee_by_client = {cid: Decimal(v or 0) for cid, v in fee_rows}

    service_rows = session.execute(
        select(ClientServiceCharge.client_id, func.sum(ClientServiceCharge.amount))
        .where(ClientServiceCharge.month == month_first)
        .group_by(ClientServiceCharge.client_id)
    ).all()
    service_by_client = {cid: Decimal(v or 0) for cid, v in service_rows}

    # Logistics proration: client fridge share of total active fridges × month
    # logistics (sum of overlapping weekly rows). R12 fixed-cost allocation.
    logistics_total = Decimal(
        session.execute(
            select(func.coalesce(func.sum(WeeklyFinancial.logistics_cost), 0)).where(
                WeeklyFinancial.year == window.start.year
            )
        ).scalar_one()
    )
    fridge_counts = dict(
        session.execute(
            select(Fridge.client_id, func.count())
            .where(Fridge.is_active.is_(True), Fridge.client_id.is_not(None))
            .group_by(Fridge.client_id)
        ).all()
    )
    total_fridges = sum(fridge_counts.values()) or 0

    clients = session.execute(select(Client.id, Client.name)).all()
    client_names = {cid: name for cid, name in clients}

    keys = (
        set(margin_by_client)
        | set(sales_by_client)
        | set(fee_by_client)
        | set(service_by_client)
        | set(fridge_counts)
    )
    keys.discard(None)

    rows: list[MonthlyAnalysisRow] = []
    for client_id in sorted(keys):
        food_margin = margin_by_client.get(client_id, Decimal("0"))
        sales, _items = sales_by_client.get(client_id, (Decimal("0"), 0))
        fee_share = fee_by_client.get(client_id, Decimal("0")) / Decimal("12")
        service_additionals = service_by_client.get(client_id, Decimal("0"))
        pos_fee = sales * pos_fee_pct
        if total_fridges:
            fraction = Decimal(fridge_counts.get(client_id, 0)) / Decimal(total_fridges)
        else:
            fraction = Decimal("0")
        logistics_share = fraction * logistics_total
        net = (
            fee_share
            + food_margin
            + service_additionals
            - logistics_share
            - pos_fee
        )
        rows.append(
            MonthlyAnalysisRow(
                key_id=client_id,
                key_name=client_names.get(client_id, f"client {client_id}"),
                food_margin=to_cents(food_margin),
                sales=to_cents(sales),
                pos_fee=to_cents(pos_fee),
                fee_share=to_cents(fee_share),
                service_additionals=to_cents(service_additionals),
                logistics_share=to_cents(logistics_share),
                net_margin=to_cents(net),
            )
        )
    return rows


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
    margin_by: dict, sales_by: dict, rfid_rate: Decimal, names: dict
) -> list[MonthlyAnalysisRow]:
    keys = set(margin_by) | set(sales_by)
    keys.discard(None)
    rows: list[MonthlyAnalysisRow] = []
    for key in sorted(keys):
        food_margin = margin_by.get(key, Decimal("0"))
        _sales, items = sales_by.get(key, (Decimal("0"), 0))
        rfid_fee = rfid_rate * Decimal(items)
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


# ===========================================================================
# Fridge report (formerly GSV) - per-product rows + summary
# ===========================================================================


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
    total_added_qty: int
    food_cost: int
    revenue: int
    margin: int
    margin_pct: Decimal | None  # 0..1 fraction of ex-VAT revenue, 4 decimals


def build_fridge_report(
    session: Session,
    fridge_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
) -> FridgeReportData:
    """Compute the enriched fridge report (rows + summary) for a date window.

    Rows: each product ADDED (valid tags only) to the fridge in the window, with
    its added quantity and unit buying/selling prices (per-fridge selling-price
    override applied when present). Summary: total added qty, food cost (added
    basis), sales revenue, and food margin in euros and as a 0..1 fraction of the
    ex-VAT revenue.
    """
    # Select only the columns needed (not the whole ORM entity) so the report is
    # independent of any not-yet-migrated Fridge columns and avoids over-fetching.
    fridge_name = session.execute(
        select(Fridge.friendly_name).where(Fridge.id == fridge_id)
    ).scalar_one_or_none()
    if fridge_name is None:
        raise ApiError(404, "not_found", f"fridge {fridge_id} not found")
    if date_to < date_from:
        raise ApiError(422, "unprocessable_entity", "date_to cannot precede date_from")

    start = datetime.datetime.combine(
        date_from, datetime.time.min, tzinfo=datetime.timezone.utc
    )
    end = datetime.datetime.combine(
        date_to + datetime.timedelta(days=1),
        datetime.time.min,
        tzinfo=datetime.timezone.utc,
    )

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
            RestockEvent.occurred_at >= start,
            RestockEvent.occurred_at < end,
            RestockEvent.action == RestockAction.added,
            RestockEvent.tag_status == TagStatus.valid,
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
    food_cost = Decimal("0")
    for product_id, code, name, category, added_qty, buying, selling in row_records:
        added_qty = int(added_qty)
        total_added_qty += added_qty
        food_cost += Decimal(added_qty) * Decimal(buying)
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

    revenue = Decimal(
        session.execute(
            select(func.coalesce(func.sum(SalesEvent.unit_price), 0)).where(
                SalesEvent.fridge_id == fridge_id,
                SalesEvent.sold_at >= start,
                SalesEvent.sold_at < end,
                SalesEvent.is_refunded.is_(False),
            )
        ).scalar_one()
    )

    revenue_ex_vat = revenue / VAT_DIVISOR
    margin = revenue_ex_vat - food_cost
    margin_pct = (
        (margin / revenue_ex_vat).quantize(_FOUR_PLACES)
        if revenue_ex_vat > 0
        else None
    )

    return FridgeReportData(
        fridge_id=fridge_id,
        fridge_name=fridge_name,
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        total_added_qty=total_added_qty,
        food_cost=to_cents(food_cost),
        revenue=to_cents(revenue),
        margin=to_cents(margin),
        margin_pct=margin_pct,
    )


def get_fridge_gsv_report(
    session: Session,
    fridge_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
) -> FridgeReportRead:
    """JSON view of the fridge report (per-product rows + summary KPIs)."""
    data = build_fridge_report(session, fridge_id, date_from, date_to)
    return FridgeReportRead(
        fridge_id=data.fridge_id,
        date_from=data.date_from,
        date_to=data.date_to,
        added_qty=data.total_added_qty,
        food_cost=data.food_cost,
        revenue=data.revenue,
        margin=data.margin,
        margin_pct=data.margin_pct,
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
