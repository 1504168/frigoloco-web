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
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.enums import (
    AlertType,
    DispatchStatus,
    LineSource,
    StockMovementType,
)
from app.models.master import Category, Fridge, FridgeProductPrice, Product
from app.models.operations import (
    Alert,
    Dispatch,
    DispatchLine,
    StockMovement,
)
from app.models.planning import ForecastRun, WeeklyMenu
from app.schemas.masters import api_error
from app.services import menu_service
from app.services.menu_allocation_service import compute_allocation
from app.services.stock_service import (
    is_stock_non_negative_error,
    record_audit,
    resolve_delivery_date,
)

_EDITABLE_STATUSES = (DispatchStatus.draft, DispatchStatus.saved)
_CONFIRMED_STATUSES = (DispatchStatus.dispatched, DispatchStatus.reconciled)


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
    get_dispatch(dispatch_id, session)
    lines = list(
        session.execute(
            select(DispatchLine).where(DispatchLine.dispatch_id == dispatch_id)
        )
        .scalars()
        .all()
    )

    fridge_ids = sorted({line.fridge_id for line in lines})
    product_ids = sorted({line.product_id for line in lines})

    fridges = [
        _MatrixFridge(fridge_id=fridge.id, friendly_name=fridge.friendly_name)
        for fridge in session.execute(
            select(Fridge).where(Fridge.id.in_(fridge_ids)).order_by(Fridge.friendly_name)
        )
        .scalars()
        .all()
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
    return MatrixData(
        dispatch_id=dispatch_id,
        fridges=fridges,
        products=products,
        categories=categories,
        cells=cells,
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
    """Delete existing lines (optionally scoped to a category) and insert new."""
    delete_stmt = select(DispatchLine).where(DispatchLine.dispatch_id == dispatch.id)
    if category_id is not None:
        product_ids_in_cat = select(Product.id).where(Product.category_id == category_id)
        delete_stmt = delete_stmt.where(DispatchLine.product_id.in_(product_ids_in_cat))
    for existing in session.execute(delete_stmt).scalars().all():
        session.delete(existing)
    session.flush()

    written = 0
    for line in lines:
        if line.qty <= 0:
            continue
        session.add(
            DispatchLine(
                dispatch_id=dispatch.id,
                fridge_id=line.fridge_id,
                product_id=line.product_id,
                # Denormalised partition key - always the parent's delivery date.
                delivery_date=dispatch.delivery_date,
                qty=line.qty,
                source=line.source,
            )
        )
        written += 1

    if dispatch.status == DispatchStatus.draft:
        dispatch.status = DispatchStatus.saved
    return written


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


def _raise_stock_blocked(
    *, dispatch_id: int, lines: list[DispatchLine], user_id: int | None, session: Session
) -> None:
    """After a trigger rejection: log the alert (fresh tx) and raise 409."""
    requested: dict[int, int] = {}
    for line in lines:
        requested[line.product_id] = requested.get(line.product_id, 0) + line.qty

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

    details = [
        {
            "product_id": product_id,
            "requested": qty,
            "available": available.get(product_id, 0),
        }
        for product_id, qty in requested.items()
        if qty > available.get(product_id, 0)
    ]

    session.add(
        Alert(
            alert_type=AlertType.negative_blocked,
            payload={"dispatch_id": dispatch_id, "offending_lines": details},
        )
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

    product_ids = {line.product_id for line in lines}
    fridge_ids = {line.fridge_id for line in lines}
    products = {
        product.id: product
        for product in session.execute(
            select(Product).where(Product.id.in_(product_ids))
        )
        .scalars()
        .all()
    }
    overrides = {
        (price.fridge_id, price.product_id): price.sales_price
        for price in session.execute(
            select(FridgeProductPrice).where(
                FridgeProductPrice.fridge_id.in_(fridge_ids),
                FridgeProductPrice.product_id.in_(product_ids),
            )
        )
        .scalars()
        .all()
    }

    # Snapshot prices from the catalogue (per-fridge override wins on sales price).
    for line in lines:
        product = products[line.product_id]
        line.unit_purchase_price = product.purchase_price
        line.unit_sales_price = overrides.get(
            (line.fridge_id, line.product_id), product.sales_price
        )
        line.vat_rate = product.vat_rate
    session.flush()

    for line in lines:
        session.add(
            StockMovement(
                product_id=line.product_id,
                qty=-line.qty,
                movement_type=StockMovementType.dispatch,
                dispatch_line_id=line.id,
            )
        )
    try:
        session.flush()
    except DBAPIError as exc:
        session.rollback()
        if is_stock_non_negative_error(exc):
            _raise_stock_blocked(
                dispatch_id=dispatch_id, lines=lines, user_id=user_id, session=session
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
    *, year: int, week: int, day_name: str, session: Session
) -> MatrixData:
    """Preview dispatch lines seeded from the saved menu (NOT persisted, D2).

    The saved menu grid and the dispatch matrix share the same fridge x product
    shape, so the menu quantities map straight onto a dispatch preview
    (``dispatch_id = 0`` marks it unsaved).
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
        ],
        categories=[
            _MatrixCategory(
                category_id=category.category_id,
                category_name=category.category_name,
                product_ids=category.product_ids,
            )
            for category in grid.categories
        ],
        cells=[
            _MatrixCell(fridge_id=cell.fridge_id, product_id=cell.product_id, qty=cell.qty)
            for cell in grid.cells
        ],
    )


def _dispatch_for_delivery_date(
    delivery_date: datetime.date, session: Session
) -> Dispatch | None:
    return session.execute(
        select(Dispatch).where(Dispatch.delivery_date == delivery_date)
    ).scalars().first()


def save_planned(
    *,
    year: int,
    week: int,
    day_name: str,
    lines: list[LineInput],
    overwrite: bool,
    user_id: int | None,
    session: Session,
) -> Dispatch:
    """Save a PLANNED dispatch for the key - status 'saved', NO stock effect (D2).

    Stock is only ever moved by :func:`confirm_dispatch` ("create individual
    dispatch"); saving merely records the planned lines. A dispatch already
    existing for the key yields ``409 {code:"exists"}`` unless ``overwrite`` is
    set (delete prior lines + reinsert in one transaction + audit). A dispatch
    already confirmed cannot be overwritten.
    """
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
        if not overwrite:
            raise api_error(
                409,
                "exists",
                "A saved dispatch already exists for this key; resend with overwrite=true",
                {"delivery_date": delivery_date.isoformat(), "dispatch_id": existing.id},
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
        dispatch=dispatch, lines=lines, category_id=None, session=session
    )
    record_audit(
        session,
        action="dispatch.save.overwrite" if existing is not None else "dispatch.save",
        entity="dispatches",
        entity_id=dispatch.id,
        after={
            "delivery_date": delivery_date.isoformat(),
            "status": "saved",
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
