"""Dispatch batch lifecycle (R7) and the confirm transaction (§4a of the brief).

Batch identity is one row per ``delivery_date`` (DB UNIQUE). Confirm is a single
all-or-nothing transaction: validate status, block past dates without ``force``,
snapshot line prices from the catalogue, then write one negative ``dispatch``
movement per line. The DB non-negativity trigger is the source of truth - a
rejection is rolled back, recorded as a ``negative_blocked`` alert, and surfaced
as HTTP 409 ``stock_blocked``.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.enums import (
    DispatchStatus,
    LineSource,
    StockMovementType,
)
from app.models.master import (
    Category,
    FridgeDeliveryConfig,
    Product,
)
from app.models.operations import (
    Dispatch,
    DispatchLine,
    StockMovement,
)
from app.models.planning import ForecastRun, WeeklyMenu
from app.schemas.masters import api_error
from app.services import fridge_stock_service, menu_service
from app.services.alerts_service import OffendingLine, raise_stock_blocked_alert
from app.services.menu_allocation_service import compute_allocation
from app.services.stock_service import (
    is_stock_non_negative_error,
    record_audit,
    resolve_delivery_date,
)

_EDITABLE_STATUSES = (DispatchStatus.draft, DispatchStatus.saved)
_CONFIRMED_STATUSES = (DispatchStatus.dispatched, DispatchStatus.reconciled)

# The per-fridge sales price override wins over the catalogue sales price.
_SNAPSHOT_LINE_PRICES_SQL = text(
    """
    UPDATE dispatch_lines dl
    SET unit_purchase_price = p.purchase_price,
        unit_sales_price = COALESCE(
            (
                SELECT fpp.sales_price
                FROM fridge_product_prices fpp
                WHERE fpp.fridge_id = dl.fridge_id
                  AND fpp.product_id = dl.product_id
            ),
            p.sales_price
        ),
        vat_rate = p.vat_rate
    FROM products p
    WHERE p.id = dl.product_id
      AND dl.dispatch_id = :dispatch_id
      AND dl.delivery_date = :delivery_date
    """
)


@dataclass(frozen=True)
class _MatrixFridge:
    fridge_id: int
    friendly_name: str


@dataclass(frozen=True)
class _MatrixProduct:
    product_id: int
    product_name: str
    category_id: int


@dataclass(frozen=True)
class _MatrixCell:
    fridge_id: int
    product_id: int
    qty: int


@dataclass(frozen=True)
class _MatrixCategory:
    category_id: int
    category_name: str
    product_ids: list[int]


@dataclass(frozen=True)
class MatrixData:
    dispatch_id: int
    fridges: list[_MatrixFridge]
    products: list[_MatrixProduct]
    categories: list[_MatrixCategory]
    cells: list[_MatrixCell]
    # Cost of the lines at their snapshot prices; only set once dispatched.
    dispatched_cost_total: int | None = None


def create_dispatch(
    *, delivery_date: datetime.date, user_id: int | None, session: Session
) -> Dispatch:
    iso_year, iso_week, weekday = delivery_date.isocalendar()
    existing = session.execute(
        select(Dispatch).where(Dispatch.delivery_date == delivery_date)
    ).scalars().first()
    if existing is not None:
        raise api_error(
            409,
            "conflict",
            "A dispatch already exists for this delivery date",
            {"delivery_date": delivery_date.isoformat(), "dispatch_id": existing.id},
        )

    dispatch = Dispatch(
        delivery_date=delivery_date,
        iso_week=iso_week,
        weekday=weekday,
        status=DispatchStatus.draft,
        created_by=user_id,
    )
    session.add(dispatch)
    record_audit(
        session,
        action="dispatch.create",
        entity="dispatches",
        entity_id=None,
        after={"delivery_date": delivery_date.isoformat()},
        user_id=user_id,
    )
    session.commit()
    session.refresh(dispatch)
    return dispatch


def list_dispatches(
    *, status: DispatchStatus | None, limit: int, offset: int, session: Session
) -> tuple[list[Dispatch], int]:
    stmt = select(Dispatch)
    count_stmt = select(func.count()).select_from(Dispatch)
    if status is not None:
        stmt = stmt.where(Dispatch.status == status)
        count_stmt = count_stmt.where(Dispatch.status == status)
    total = session.execute(count_stmt).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(Dispatch.delivery_date.desc()).limit(limit).offset(offset)
        )
        .scalars()
        .all()
    )
    return rows, int(total)


def get_dispatch(dispatch_id: int, session: Session) -> Dispatch:
    dispatch = session.get(Dispatch, dispatch_id)
    if dispatch is None:
        raise api_error(404, "not_found", "Dispatch not found", {"dispatch_id": dispatch_id})
    return dispatch


def get_matrix(dispatch_id: int, session: Session) -> MatrixData:
    dispatch = get_dispatch(dispatch_id, session)
    lines = list(
        session.execute(
            select(DispatchLine).where(DispatchLine.dispatch_id == dispatch_id)
        )
        .scalars()
        .all()
    )

    product_ids = sorted({line.product_id for line in lines})
    delivery_day_fridges = menu_service.list_delivery_day_fridges(
        delivery_date=dispatch.delivery_date,
        fridge_ids_with_lines={line.fridge_id for line in lines},
        session=session,
    )
    fridges = [
        _MatrixFridge(fridge_id=fridge.fridge_id, friendly_name=fridge.friendly_name)
        for fridge in delivery_day_fridges
    ]
    product_rows = list(
        session.execute(
            select(Product).where(Product.id.in_(product_ids)).order_by(Product.name)
        )
        .scalars()
        .all()
    )
    products = [
        _MatrixProduct(
            product_id=product.id,
            product_name=product.name,
            category_id=product.category_id,
        )
        for product in product_rows
    ]

    category_names = {
        category.id: category.name
        for category in session.execute(select(Category)).scalars().all()
    }
    products_by_category: dict[int, list[int]] = {}
    for product in product_rows:
        products_by_category.setdefault(product.category_id, []).append(product.id)
    categories = [
        _MatrixCategory(
            category_id=category_id,
            category_name=category_names.get(category_id, ""),
            product_ids=pids,
        )
        for category_id, pids in sorted(products_by_category.items())
    ]

    cells = [
        _MatrixCell(fridge_id=line.fridge_id, product_id=line.product_id, qty=line.qty)
        for line in lines
    ]
    dispatched_cost_total = None
    if dispatch.status in _CONFIRMED_STATUSES:
        dispatched_cost_total = sum(line.qty * line.unit_purchase_price for line in lines)
    return MatrixData(
        dispatch_id=dispatch_id,
        fridges=fridges,
        products=products,
        categories=categories,
        cells=cells,
        dispatched_cost_total=dispatched_cost_total,
    )


def _require_editable(dispatch: Dispatch) -> None:
    if dispatch.status not in _EDITABLE_STATUSES:
        raise api_error(
            409,
            "conflict",
            "Dispatch lines can only be edited while draft or saved",
            {"dispatch_id": dispatch.id, "status": dispatch.status.value},
        )


@dataclass(frozen=True)
class LineInput:
    fridge_id: int
    product_id: int
    qty: int
    source: LineSource


def _replace_lines(
    *,
    dispatch: Dispatch,
    lines: list[LineInput],
    category_id: int | None,
    session: Session,
) -> int:
    """Delete existing lines (optionally scoped to a category) and insert new.

    Bulk statements on purpose: the composite (id, delivery_date) primary key makes
    ORM adds and deletes run one round trip per row.
    """
    delete_stmt = delete(DispatchLine).where(DispatchLine.dispatch_id == dispatch.id)
    if category_id is not None:
        product_ids_in_cat = select(Product.id).where(Product.category_id == category_id)
        delete_stmt = delete_stmt.where(DispatchLine.product_id.in_(product_ids_in_cat))
    session.execute(delete_stmt)

    new_line_rows = [
        {
            "dispatch_id": dispatch.id,
            "fridge_id": line.fridge_id,
            "product_id": line.product_id,
            # Denormalised partition key - always the parent's delivery date.
            "delivery_date": dispatch.delivery_date,
            "qty": line.qty,
            "source": line.source,
        }
        for line in lines
        if line.qty > 0
    ]
    if new_line_rows:
        session.execute(insert(DispatchLine), new_line_rows)

    if dispatch.status == DispatchStatus.draft:
        dispatch.status = DispatchStatus.saved
    return len(new_line_rows)


def replace_lines(
    *,
    dispatch_id: int,
    lines: list[LineInput],
    category_id: int | None,
    user_id: int | None,
    session: Session,
) -> int:
    dispatch = get_dispatch(dispatch_id, session)
    _require_editable(dispatch)
    written = _replace_lines(
        dispatch=dispatch, lines=lines, category_id=category_id, session=session
    )
    record_audit(
        session,
        action="dispatch.replace_lines",
        entity="dispatches",
        entity_id=dispatch_id,
        after={"lines_written": written, "category_id": category_id},
        user_id=user_id,
    )
    session.commit()
    return written


def apply_forecast(
    *, dispatch_id: int, user_id: int | None, session: Session
) -> int:
    dispatch = get_dispatch(dispatch_id, session)
    _require_editable(dispatch)

    run = session.execute(
        select(ForecastRun)
        .where(ForecastRun.delivery_date == dispatch.delivery_date)
        .order_by(ForecastRun.run_at.desc(), ForecastRun.id.desc())
        .limit(1)
    ).scalars().first()
    if run is None:
        raise api_error(
            409,
            "conflict",
            "No forecast run exists for this dispatch's delivery date",
            {"delivery_date": dispatch.delivery_date.isoformat()},
        )

    iso_year, iso_week, _weekday = dispatch.delivery_date.isocalendar()
    menu = session.execute(
        select(WeeklyMenu)
        .where(WeeklyMenu.year == iso_year, WeeklyMenu.iso_week == iso_week)
        .order_by(WeeklyMenu.status.desc(), WeeklyMenu.id.desc())
        .limit(1)
    ).scalars().first()
    if menu is None:
        raise api_error(
            409,
            "conflict",
            "No weekly menu exists for this dispatch's ISO week",
            {"year": iso_year, "iso_week": iso_week},
        )

    allocation = compute_allocation(
        menu_id=menu.id, forecast_run_id=run.id, session=session
    )
    lines = [
        LineInput(
            fridge_id=line.fridge_id,
            product_id=line.product_id,
            qty=line.qty,
            source=LineSource.forecast,
        )
        for line in allocation
    ]
    written = _replace_lines(
        dispatch=dispatch, lines=lines, category_id=None, session=session
    )
    record_audit(
        session,
        action="dispatch.apply_forecast",
        entity="dispatches",
        entity_id=dispatch_id,
        after={
            "forecast_run_id": run.id,
            "menu_id": menu.id,
            "lines_written": written,
        },
        user_id=user_id,
    )
    session.commit()
    return written


def _count_movements(dispatch_id: int, session: Session) -> int:
    return int(
        session.execute(
            select(func.count())
            .select_from(StockMovement)
            .join(DispatchLine, DispatchLine.id == StockMovement.dispatch_line_id)
            .where(DispatchLine.dispatch_id == dispatch_id)
        ).scalar_one()
    )


def _requested_qty_by_product(lines: list[DispatchLine]) -> dict[int, int]:
    requested: dict[int, int] = {}
    for line in lines:
        requested[line.product_id] = requested.get(line.product_id, 0) + line.qty
    return requested


def _raise_stock_blocked(
    *,
    dispatch_id: int,
    requested: dict[int, int],
    user_id: int | None,
    session: Session,
) -> None:
    """After a trigger rejection: log the alert (fresh tx) and raise 409."""
    available: dict[int, int] = {}
    if requested:
        for row in session.execute(
            text(
                "SELECT product_id, physical_qty FROM v_stock_balances "
                "WHERE product_id = ANY(:ids)"
            ),
            {"ids": list(requested)},
        ).all():
            available[row.product_id] = int(row.physical_qty)

    offending_lines = [
        OffendingLine(
            product_id=product_id,
            requested=qty,
            available=available.get(product_id, 0),
        )
        for product_id, qty in requested.items()
        if qty > available.get(product_id, 0)
    ]
    details = [asdict(line) for line in offending_lines]

    raise_stock_blocked_alert(
        session,
        dispatch_id=dispatch_id,
        offending_lines=offending_lines,
    )
    record_audit(
        session,
        action="dispatch.confirm_blocked",
        entity="dispatches",
        entity_id=dispatch_id,
        after={"offending_lines": details},
        user_id=user_id,
    )
    session.commit()
    raise api_error(
        409,
        "stock_blocked",
        "Confirming would take stock below zero",
        details or [{"dispatch_id": dispatch_id}],
    )


def confirm_dispatch(
    *, dispatch_id: int, force: bool, user_id: int | None, session: Session
) -> tuple[Dispatch, int]:
    """Confirm a dispatch in one transaction. Returns (dispatch, movements_created)."""
    dispatch = session.get(Dispatch, dispatch_id, with_for_update=True)
    if dispatch is None:
        raise api_error(404, "not_found", "Dispatch not found", {"dispatch_id": dispatch_id})

    if dispatch.status in _CONFIRMED_STATUSES:  # idempotent re-confirm
        session.commit()
        return dispatch, _count_movements(dispatch_id, session)

    today = datetime.date.today()
    if dispatch.delivery_date < today and not force:
        raise api_error(
            409,
            "past_date_requires_force",
            "Delivery date is in the past; resubmit with force=true to confirm",
            {"delivery_date": dispatch.delivery_date.isoformat()},
        )

    lines = list(
        session.execute(
            select(DispatchLine).where(DispatchLine.dispatch_id == dispatch_id)
        )
        .scalars()
        .all()
    )
    if not lines:
        raise api_error(
            409,
            "conflict",
            "Cannot confirm a dispatch with no lines",
            {"dispatch_id": dispatch_id},
        )

    # Read before the flush: a rollback expires the lines, and re-reading each costs a query.
    requested_by_product = _requested_qty_by_product(lines)
    session.execute(
        _SNAPSHOT_LINE_PRICES_SQL,
        {"dispatch_id": dispatch_id, "delivery_date": dispatch.delivery_date},
    )

    for line in lines:
        session.add(
            StockMovement(
                product_id=line.product_id,
                qty=-line.qty,
                movement_type=StockMovementType.dispatch,
                dispatch_line_id=line.id,
                created_by=user_id,
            )
        )
    try:
        session.flush()
    except DBAPIError as exc:
        session.rollback()
        if is_stock_non_negative_error(exc):
            _raise_stock_blocked(
                dispatch_id=dispatch_id,
                requested=requested_by_product,
                user_id=user_id,
                session=session,
            )
        raise

    dispatch.status = DispatchStatus.dispatched
    dispatch.confirmed_by = user_id
    dispatch.confirmed_at = datetime.datetime.now(datetime.timezone.utc)
    record_audit(
        session,
        action="dispatch.confirm",
        entity="dispatches",
        entity_id=dispatch_id,
        before={"status": "saved"},
        after={"status": "dispatched", "movements_created": len(lines)},
        user_id=user_id,
    )
    session.commit()
    session.refresh(dispatch)
    return dispatch, len(lines)


# ===========================================================================
# D2 - (iso_year, week_no, day_name) workflow: import-from-menu, save (PLANNED,
# no stock), load-saved, create-individual (the only stock-writing path).
# ===========================================================================


def import_from_menu(
    *,
    year: int,
    week: int,
    day_name: str,
    category_id: int | None = None,
    session: Session,
) -> MatrixData:
    """Preview dispatch lines seeded from the saved menu (NOT persisted, D2).

    The saved menu grid and the dispatch matrix share the same fridge x product
    shape, so the menu quantities map straight onto a dispatch preview
    (``dispatch_id = 0`` marks it unsaved). When ``category_id`` is set, only
    that category is previewed (the caller merges it into the existing matrix).
    """
    grid = menu_service.get_saved_menu(
        year=year, week=week, day_name=day_name, session=session
    )
    if grid is None:
        raise api_error(
            404,
            "not_found",
            "No saved menu to import from for this key",
            {"year": year, "week": week, "day_name": day_name},
        )

    category_of = {product.product_id: product.category_id for product in grid.products}
    in_scope = (
        (lambda cat_id: cat_id == category_id)
        if category_id is not None
        else (lambda cat_id: True)
    )
    return MatrixData(
        dispatch_id=0,
        fridges=[
            _MatrixFridge(fridge_id=fridge.fridge_id, friendly_name=fridge.friendly_name)
            for fridge in grid.fridges
        ],
        products=[
            _MatrixProduct(
                product_id=product.product_id,
                product_name=product.product_name,
                category_id=product.category_id,
            )
            for product in grid.products
            if in_scope(product.category_id)
        ],
        categories=[
            _MatrixCategory(
                category_id=category.category_id,
                category_name=category.category_name,
                product_ids=category.product_ids,
            )
            for category in grid.categories
            if in_scope(category.category_id)
        ],
        cells=[
            _MatrixCell(fridge_id=cell.fridge_id, product_id=cell.product_id, qty=cell.qty)
            for cell in grid.cells
            if in_scope(category_of.get(cell.product_id))
        ],
    )


def _dispatch_for_delivery_date(
    delivery_date: datetime.date, session: Session
) -> Dispatch | None:
    return session.execute(
        select(Dispatch).where(Dispatch.delivery_date == delivery_date)
    ).scalars().first()


def _dispatch_category_has_lines(
    dispatch_id: int, category_id: int, session: Session
) -> bool:
    """True when the saved dispatch already holds lines for this category."""
    return bool(
        session.execute(
            select(DispatchLine.id)
            .join(Product, Product.id == DispatchLine.product_id)
            .where(
                DispatchLine.dispatch_id == dispatch_id,
                Product.category_id == category_id,
            )
            .limit(1)
        ).scalar()
    )


def _validate_lines_in_category(
    lines: list[LineInput], category_id: int, session: Session
) -> None:
    """Reject a category-scoped save whose lines reach outside that category."""
    product_ids = {line.product_id for line in lines}
    if not product_ids:
        return
    category_of = {
        product.id: product.category_id
        for product in session.execute(
            select(Product).where(Product.id.in_(product_ids))
        )
        .scalars()
        .all()
    }
    outside = sorted(
        pid for pid in product_ids if category_of.get(pid) != category_id
    )
    if outside:
        raise api_error(
            422,
            "validation_error",
            "Dispatch lines contain products outside the target category",
            {"category_id": category_id, "product_ids": outside},
        )


def save_planned(
    *,
    year: int,
    week: int,
    day_name: str,
    lines: list[LineInput],
    overwrite: bool,
    category_id: int | None = None,
    user_id: int | None,
    session: Session,
) -> Dispatch:
    """Save a PLANNED dispatch for the key - status 'saved', NO stock effect (D2).

    Stock is only ever moved by :func:`confirm_dispatch` ("create individual
    dispatch"); saving merely records the planned lines. A dispatch already
    existing for the key yields ``409 {code:"exists"}`` unless ``overwrite`` is
    set (delete prior lines + reinsert in one transaction + audit). A dispatch
    already confirmed cannot be overwritten.

    When ``category_id`` is set, only that category's lines are replaced (the
    Excel "save one category" flow): other categories' planned lines stay intact,
    and the ``exists`` conflict fires only if THAT category already has lines.
    """
    scoped = category_id is not None
    if scoped:
        _validate_lines_in_category(lines, category_id, session)

    delivery_date = resolve_delivery_date(year, week, day_name)
    iso_year, iso_week, weekday = delivery_date.isocalendar()
    existing = _dispatch_for_delivery_date(delivery_date, session)

    if existing is not None:
        if existing.status in _CONFIRMED_STATUSES:
            raise api_error(
                409,
                "conflict",
                "Dispatch already created (dispatched); cannot overwrite",
                {"delivery_date": delivery_date.isoformat(), "status": existing.status.value},
            )
        conflict = (
            _dispatch_category_has_lines(existing.id, category_id, session)
            if scoped
            else True
        )
        if conflict and not overwrite:
            raise api_error(
                409,
                "exists",
                "A saved dispatch already exists for this key; resend with overwrite=true",
                {
                    "delivery_date": delivery_date.isoformat(),
                    "dispatch_id": existing.id,
                    "category_id": category_id,
                },
            )
        dispatch = existing
    else:
        dispatch = Dispatch(
            delivery_date=delivery_date,
            iso_week=iso_week,
            weekday=weekday,
            status=DispatchStatus.saved,
            created_by=user_id,
        )
        session.add(dispatch)
        session.flush()  # assign dispatch.id

    written = _replace_lines(
        dispatch=dispatch, lines=lines, category_id=category_id, session=session
    )
    if scoped:
        action = "dispatch.save.category"
    elif existing is not None:
        action = "dispatch.save.overwrite"
    else:
        action = "dispatch.save"
    record_audit(
        session,
        action=action,
        entity="dispatches",
        entity_id=dispatch.id,
        after={
            "delivery_date": delivery_date.isoformat(),
            "status": "saved",
            "category_id": category_id,
            "lines_written": written,
        },
        user_id=user_id,
    )
    session.commit()
    session.refresh(dispatch)
    return dispatch


def get_saved_by_key(
    *, year: int, week: int, day_name: str, session: Session
) -> Dispatch | None:
    """Load the dispatch for the (year, week, day_name) key (import-from-database)."""
    delivery_date = resolve_delivery_date(year, week, day_name)
    return _dispatch_for_delivery_date(delivery_date, session)


@dataclass(frozen=True)
class WithdrawalItem:
    fridge_id: int
    friendly_name: str
    product_id: int
    product_code: str
    product_name: str
    units_expiring: int
    earliest_expiry: datetime.datetime


def withdrawal_list(
    *, year: int, week: int, day_name: str, session: Session
) -> list[WithdrawalItem]:
    """Products a driver must PULL from each fridge on this delivery day (slide 5).

    For every fridge with a delivery config on this weekday, any in-fridge unit
    whose captured expiry falls BEFORE the coverage end (next delivery, or the first
    closed day before it) is listed for withdrawal. This is the exact complement of
    the forecast's residual-stock deduction (fridge_stock_service).
    """
    delivery_date = resolve_delivery_date(year, week, day_name)
    delivering_fridge_ids = list(
        session.execute(
            select(FridgeDeliveryConfig.fridge_id).where(
                FridgeDeliveryConfig.weekday == delivery_date.isoweekday()
            )
        ).scalars()
    )
    coverage_end_by_fridge = fridge_stock_service.load_coverage_ends(
        delivery_date=delivery_date,
        fridge_ids=delivering_fridge_ids,
        session=session,
    )

    items: list[WithdrawalItem] = []
    for fridge_id, window_end in coverage_end_by_fridge.items():
        rows = session.execute(
            text(
                "SELECT fs.product_id AS product_id, fs.product_code AS product_code, "
                "p.name AS product_name, f.friendly_name AS friendly_name, "
                "count(*) FILTER (WHERE ed.expiry < :window_end) AS expiring, "
                "min(ed.expiry) FILTER (WHERE ed.expiry < :window_end) AS earliest "
                "FROM fridge_stock fs "
                "JOIN products p ON p.id = fs.product_id "
                "JOIN fridges f ON f.id = fs.fridge_id "
                "CROSS JOIN LATERAL unnest(fs.expiry_dates) AS ed(expiry) "
                "WHERE fs.fridge_id = :fid AND fs.product_id IS NOT NULL "
                "GROUP BY fs.product_id, fs.product_code, p.name, f.friendly_name "
                "HAVING count(*) FILTER (WHERE ed.expiry < :window_end) > 0"
            ),
            {"fid": fridge_id, "window_end": window_end},
        ).all()
        for row in rows:
            items.append(
                WithdrawalItem(
                    fridge_id=fridge_id,
                    friendly_name=row.friendly_name,
                    product_id=int(row.product_id),
                    product_code=row.product_code,
                    product_name=row.product_name,
                    units_expiring=int(row.expiring),
                    earliest_expiry=row.earliest,
                )
            )
    items.sort(key=lambda item: (item.friendly_name, item.product_name))
    return items


def create_individual_by_key(
    *, year: int, week: int, day_name: str, force: bool, user_id: int | None, session: Session
) -> tuple[Dispatch, int]:
    """Resolve the key to its dispatch and confirm it (the ONLY stock-writing path)."""
    delivery_date = resolve_delivery_date(year, week, day_name)
    dispatch = _dispatch_for_delivery_date(delivery_date, session)
    if dispatch is None:
        raise api_error(
            404,
            "not_found",
            "No saved dispatch for this key",
            {"year": year, "week": week, "day_name": day_name},
        )
    return confirm_dispatch(
        dispatch_id=dispatch.id, force=force, user_id=user_id, session=session
    )
