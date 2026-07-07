"""Weekly menus: CRUD, copy, product membership, targets, caps, allocation."""

from __future__ import annotations

import datetime

from fastapi import Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Fridge, MenuProductCap, ProductTarget
from app.models.planning import ForecastRun, MenuProduct, WeeklyMenu
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.schemas.menus import (
    AllocateResponse,
    AllocationLineOut,
    CapItem,
    CapRead,
    CapsReplace,
    MenuGridOut,
    MenuProductsReplace,
    MenuRead,
    MenuSaveRequest,
    TargetItem,
    TargetRead,
    TargetsReplace,
)
from app.schemas.orders import PurchaseOrderRead
from app.services import menu_service, orders_service
from app.services.menu_allocation_service import compute_allocation
from app.services.menu_service import MenuLineInput
from app.services.stock_service import record_audit, resolve_delivery_date

router = make_router(prefix="/api/v1/menus", tags=["menus"])


def _get_menu_or_404(menu_id: int, session: Session) -> WeeklyMenu:
    menu = session.get(WeeklyMenu, menu_id)
    if menu is None:
        raise api_error(404, "not_found", "Menu not found", {"id": menu_id})
    return menu


def _require_fridge(fridge_id: int, session: Session) -> Fridge:
    fridge = session.get(Fridge, fridge_id)
    if fridge is None:
        raise api_error(404, "not_found", "Fridge not found", {"id": fridge_id})
    return fridge


# --- Menu collection -------------------------------------------------------


@router.get("", response_model=Page[MenuRead])
def list_menus(
    page: PaginationParams = Depends(pagination),
    year: int | None = Query(default=None),
    week: int | None = Query(default=None, ge=1, le=53),
    session: Session = Depends(get_db),
) -> Page[MenuRead]:
    stmt = select(WeeklyMenu)
    count_stmt = select(func.count()).select_from(WeeklyMenu)
    if year is not None:
        stmt = stmt.where(WeeklyMenu.year == year)
        count_stmt = count_stmt.where(WeeklyMenu.year == year)
    if week is not None:
        stmt = stmt.where(WeeklyMenu.iso_week == week)
        count_stmt = count_stmt.where(WeeklyMenu.iso_week == week)
    total = session.execute(count_stmt).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(WeeklyMenu.year.desc(), WeeklyMenu.iso_week.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    return Page(
        items=[MenuRead.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=MenuRead, status_code=status.HTTP_201_CREATED)
def create_menu(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    session: Session = Depends(get_db),
) -> MenuRead:
    menu = WeeklyMenu(year=year, iso_week=week)
    session.add(menu)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "A menu already exists for this year/week", {"year": year, "week": week}
        ) from exc
    session.refresh(menu)
    return MenuRead.model_validate(menu)


# --- Workflow: import-from-forecast / save / load-saved / draft PO (D2) -----


@router.post("/import-from-forecast", response_model=MenuGridOut)
def import_menu_from_forecast(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    session: Session = Depends(get_db),
) -> MenuGridOut:
    """Seed a draft menu grid (not persisted) from the saved forecast."""
    delivery_date = resolve_delivery_date(year, week, day_name)
    grid = menu_service.import_from_forecast(
        year=year, week=week, day_name=day_name, delivery_date=delivery_date, session=session
    )
    return MenuGridOut.model_validate(grid)


@router.post("/save", response_model=MenuGridOut)
def save_menu(body: MenuSaveRequest, session: Session = Depends(get_db)) -> MenuGridOut:
    """Persist the menu grid keyed on (year, week, day_name); overwrite-confirm."""
    grid = menu_service.save_menu(
        year=body.year,
        week=body.week,
        day_name=body.day_name,
        lines=[
            MenuLineInput(fridge_id=item.fridge_id, product_id=item.product_id, qty=item.qty)
            for item in body.lines
        ],
        overwrite=body.overwrite,
        user_id=None,
        session=session,
    )
    return MenuGridOut.model_validate(grid)


@router.get("/saved", response_model=MenuGridOut)
def load_saved_menu(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    session: Session = Depends(get_db),
) -> MenuGridOut:
    """Load a previously saved menu grid for the key."""
    grid = menu_service.get_saved_menu(
        year=year, week=week, day_name=day_name, session=session
    )
    if grid is None:
        raise api_error(
            404,
            "not_found",
            "No saved menu for this key",
            {"year": year, "week": week, "day_name": day_name},
        )
    return MenuGridOut.model_validate(grid)


@router.post("/draft-purchase-orders", response_model=PurchaseOrderRead)
def draft_purchase_order_from_menu(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    supplier_id: int = Query(...),
    session: Session = Depends(get_db),
) -> PurchaseOrderRead:
    """Draft one pending PO for a supplier from the saved menu's quantities.

    Mirror of the Excel "Order details (va chercher dans le menu)" button.
    """
    delivery_date = resolve_delivery_date(year, week, day_name)
    quantities = menu_service.aggregate_supplier_quantities(
        year=year, week=week, day_name=day_name, supplier_id=supplier_id, session=session
    )
    try:
        return orders_service.draft_from_menu(
            session,
            supplier_id=supplier_id,
            product_quantities=quantities,
            expected_delivery_date=delivery_date,
            comment=f"Drafted from menu {year}-W{week} {day_name}",
        )
    except orders_service.ApiError as exc:
        raise api_error(exc.status_code, exc.code, exc.message, exc.details) from exc


# --- Product targets (fridge-scoped) --------------------------------------


@router.get("/product-targets", response_model=list[TargetRead])
def get_product_targets(
    fridge_id: int = Query(...), session: Session = Depends(get_db)
) -> list[TargetRead]:
    _require_fridge(fridge_id, session)
    rows = list(
        session.execute(
            select(ProductTarget)
            .where(ProductTarget.fridge_id == fridge_id)
            .order_by(ProductTarget.product_id)
        )
        .scalars()
        .all()
    )
    return [TargetRead.model_validate(row) for row in rows]


@router.put("/product-targets", response_model=list[TargetRead])
def replace_product_targets(
    body: TargetsReplace,
    fridge_id: int = Query(...),
    session: Session = Depends(get_db),
) -> list[TargetRead]:
    _require_fridge(fridge_id, session)
    product_ids = [item.product_id for item in body.items]
    if len(product_ids) != len(set(product_ids)):
        raise api_error(422, "validation_error", "Duplicate product_id in payload", None)
    for existing in session.execute(
        select(ProductTarget).where(ProductTarget.fridge_id == fridge_id)
    ).scalars().all():
        session.delete(existing)
    session.flush()
    for item in body.items:
        session.add(
            ProductTarget(
                fridge_id=fridge_id, product_id=item.product_id, target_qty=item.target_qty
            )
        )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(409, "conflict", "Invalid product reference in targets", None) from exc
    return get_product_targets(fridge_id, session)


# --- Menu caps (fridge-scoped) --------------------------------------------


@router.get("/menu-caps", response_model=list[CapRead])
def get_menu_caps(
    fridge_id: int = Query(...), session: Session = Depends(get_db)
) -> list[CapRead]:
    _require_fridge(fridge_id, session)
    rows = list(
        session.execute(
            select(MenuProductCap)
            .where(MenuProductCap.fridge_id == fridge_id)
            .order_by(MenuProductCap.product_id)
        )
        .scalars()
        .all()
    )
    return [CapRead.model_validate(row) for row in rows]


@router.put("/menu-caps", response_model=list[CapRead])
def replace_menu_caps(
    body: CapsReplace,
    fridge_id: int = Query(...),
    session: Session = Depends(get_db),
) -> list[CapRead]:
    _require_fridge(fridge_id, session)
    product_ids = [item.product_id for item in body.items]
    if len(product_ids) != len(set(product_ids)):
        raise api_error(422, "validation_error", "Duplicate product_id in payload", None)
    for existing in session.execute(
        select(MenuProductCap).where(MenuProductCap.fridge_id == fridge_id)
    ).scalars().all():
        session.delete(existing)
    session.flush()
    for item in body.items:
        session.add(
            MenuProductCap(
                fridge_id=fridge_id, product_id=item.product_id, max_qty=item.max_qty
            )
        )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(409, "conflict", "Invalid product reference in caps", None) from exc
    return get_menu_caps(fridge_id, session)


# --- Menu item routes ------------------------------------------------------


@router.get("/{menu_id}", response_model=MenuRead)
def get_menu(menu_id: int, session: Session = Depends(get_db)) -> MenuRead:
    return MenuRead.model_validate(_get_menu_or_404(menu_id, session))


@router.post("/{menu_id}/copy-from/{other_id}", response_model=MenuRead)
def copy_menu_from(
    menu_id: int, other_id: int, session: Session = Depends(get_db)
) -> MenuRead:
    menu = _get_menu_or_404(menu_id, session)
    source = _get_menu_or_404(other_id, session)
    for existing in session.execute(
        select(MenuProduct).where(MenuProduct.menu_id == menu_id)
    ).scalars().all():
        session.delete(existing)
    session.flush()
    source_products = session.execute(
        select(MenuProduct.product_id).where(MenuProduct.menu_id == source.id)
    ).scalars().all()
    for product_id in source_products:
        session.add(MenuProduct(menu_id=menu_id, product_id=product_id))
    menu.copied_from_id = source.id
    session.commit()
    session.refresh(menu)
    return MenuRead.model_validate(menu)


@router.put("/{menu_id}/products", response_model=MenuRead)
def replace_menu_products(
    menu_id: int, body: MenuProductsReplace, session: Session = Depends(get_db)
) -> MenuRead:
    menu = _get_menu_or_404(menu_id, session)
    unique_ids = list(dict.fromkeys(body.product_ids))
    for existing in session.execute(
        select(MenuProduct).where(MenuProduct.menu_id == menu_id)
    ).scalars().all():
        session.delete(existing)
    session.flush()
    for product_id in unique_ids:
        session.add(MenuProduct(menu_id=menu_id, product_id=product_id))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(422, "validation_error", "Unknown product in menu list", None) from exc
    session.refresh(menu)
    return MenuRead.model_validate(menu)


@router.post("/{menu_id}/allocate", response_model=AllocateResponse)
def allocate_menu(
    menu_id: int,
    forecast_run_id: int | None = Query(default=None),
    delivery_date: datetime.date | None = Query(default=None),
    session: Session = Depends(get_db),
) -> AllocateResponse:
    _get_menu_or_404(menu_id, session)

    run: ForecastRun | None
    if forecast_run_id is not None:
        run = session.get(ForecastRun, forecast_run_id)
    else:
        stmt = select(ForecastRun)
        if delivery_date is not None:
            stmt = stmt.where(ForecastRun.delivery_date == delivery_date)
        run = session.execute(
            stmt.order_by(ForecastRun.run_at.desc(), ForecastRun.id.desc()).limit(1)
        ).scalars().first()
    if run is None:
        raise api_error(404, "not_found", "No forecast run found to allocate from", None)

    lines = compute_allocation(menu_id=menu_id, forecast_run_id=run.id, session=session)
    record_audit(
        session,
        action="menu.allocate",
        entity="weekly_menus",
        entity_id=menu_id,
        after={"forecast_run_id": run.id, "lines": len(lines)},
    )
    session.commit()
    return AllocateResponse(
        menu_id=menu_id,
        forecast_run_id=run.id,
        lines=[
            AllocationLineOut(
                fridge_id=line.fridge_id,
                category_id=line.category_id,
                product_id=line.product_id,
                qty=line.qty,
                source=line.source,
            )
            for line in lines
        ],
    )
