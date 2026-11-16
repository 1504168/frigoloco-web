"""Dispatch batches: CRUD, matrix, line editing, apply-forecast, confirm."""

from __future__ import annotations

from fastapi import Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import DispatchStatus
from app.models.master import User
from app.schemas.dispatches import (
    ConfirmRequest,
    ConfirmResult,
    DispatchCreate,
    DispatchLinesReplace,
    DispatchMatrix,
    DispatchRead,
    DispatchSaveRequest,
    StockFitOut,
    StockFitRequest,
    WarmDishLineOut,
    WeekComparisonOut,
    WithdrawalItem,
    WithdrawalListOut,
)
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.security import get_current_user
from app.services import (
    dispatch_export_service,
    dispatch_overview_service,
    dispatch_service,
    stock_fit_service,
)
from app.services.dispatch_service import LineInput

router = make_router(prefix="/api/v1/dispatches", tags=["dispatches"])


@router.get("", response_model=Page[DispatchRead])
def list_dispatches(
    page: PaginationParams = Depends(pagination),
    dispatch_status: DispatchStatus | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
) -> Page[DispatchRead]:
    rows, total = dispatch_service.list_dispatches(
        status=dispatch_status, limit=page.limit, offset=page.offset, session=session
    )
    return Page(
        items=[DispatchRead.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=DispatchRead, status_code=status.HTTP_201_CREATED)
def create_dispatch(
    body: DispatchCreate, session: Session = Depends(get_db)
) -> DispatchRead:
    dispatch = dispatch_service.create_dispatch(
        delivery_date=body.delivery_date, user_id=None, session=session
    )
    return DispatchRead.model_validate(dispatch)


# --- Workflow: import-from-menu / save (PLANNED) / load-saved / create-individual (D2)


@router.post("/import-from-menu", response_model=DispatchMatrix)
def import_dispatch_from_menu(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    category_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> DispatchMatrix:
    """Preview dispatch lines seeded from the saved menu (not persisted).

    ``category_id`` restricts the preview to a single category (the caller merges
    it into the existing matrix); omit it to pull all categories.
    """
    return DispatchMatrix.model_validate(
        dispatch_service.import_from_menu(
            year=year,
            week=week,
            day_name=day_name,
            category_id=category_id,
            session=session,
        )
    )


@router.post("/save", response_model=DispatchRead)
def save_dispatch(
    body: DispatchSaveRequest, session: Session = Depends(get_db)
) -> DispatchRead:
    """Save a PLANNED dispatch (status 'saved', NO stock effect); overwrite-confirm."""
    dispatch = dispatch_service.save_planned(
        year=body.year,
        week=body.week,
        day_name=body.day_name,
        lines=[
            LineInput(
                fridge_id=line.fridge_id,
                product_id=line.product_id,
                qty=line.qty,
                source=line.source,
            )
            for line in body.lines
        ],
        overwrite=body.overwrite,
        category_id=body.category_id,
        user_id=None,
        session=session,
    )
    return DispatchRead.model_validate(dispatch)


@router.get("/saved", response_model=DispatchRead)
def load_saved_dispatch(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    session: Session = Depends(get_db),
) -> DispatchRead:
    """Load a previously saved dispatch for the key."""
    dispatch = dispatch_service.get_saved_by_key(
        year=year, week=week, day_name=day_name, session=session
    )
    if dispatch is None:
        raise api_error(
            404,
            "not_found",
            "No saved dispatch for this key",
            {"year": year, "week": week, "day_name": day_name},
        )
    return DispatchRead.model_validate(dispatch)


@router.get("/withdrawal-list", response_model=WithdrawalListOut)
def get_withdrawal_list(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    session: Session = Depends(get_db),
) -> WithdrawalListOut:
    """Products to pull from each fridge (DLC too short for the coverage window)."""
    items = dispatch_service.withdrawal_list(
        year=year, week=week, day_name=day_name, session=session
    )
    return WithdrawalListOut(
        year=year,
        week=week,
        day_name=day_name,
        items=[WithdrawalItem.model_validate(item) for item in items],
    )


@router.post("/create-individual", response_model=ConfirmResult)
def create_individual_dispatch(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    force: bool = Query(default=False),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConfirmResult:
    """Create the individual dispatch for the key: flip to dispatched, snapshot
    prices, write the negative stock movements (the ONLY stock-writing path)."""
    dispatch, movements = dispatch_service.create_individual_by_key(
        year=year,
        week=week,
        day_name=day_name,
        force=force,
        user_id=current_user.id,
        session=session,
    )
    return ConfirmResult(
        dispatch_id=dispatch.id,
        status=dispatch.status,
        movements_created=movements,
    )


@router.post("/fit-to-stock", response_model=StockFitOut)
def fit_dispatch_to_stock(
    body: StockFitRequest,
    session: Session = Depends(get_db),
) -> StockFitOut:
    """Cut planned lines to the warehouse stock (preview only, nothing is saved)."""
    fit_lines = [
        stock_fit_service.StockFitLine(
            fridge_id=line.fridge_id,
            product_id=line.product_id,
            qty=line.qty,
        )
        for line in body.lines
    ]
    stock_fit = stock_fit_service.fit_lines_to_warehouse_stock(
        fit_lines,
        session,
        include_orders_due_by=body.include_orders_due_by,
    )
    return StockFitOut.model_validate(stock_fit)


@router.get("/warm-distribution", response_model=list[WarmDishLineOut])
def get_warm_dish_distribution(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    include_planned: bool = Query(default=False),
    session: Session = Depends(get_db),
) -> list[WarmDishLineOut]:
    """Warm dish units per day, fridge and product of an ISO week (dispatched only by default)."""
    warm_dish_lines = dispatch_overview_service.list_warm_dish_lines(
        year=year,
        week=week,
        include_planned=include_planned,
        session=session,
    )
    return [WarmDishLineOut.model_validate(line) for line in warm_dish_lines]


@router.get("/week-comparison", response_model=WeekComparisonOut)
def get_week_comparison(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    session: Session = Depends(get_db),
) -> WeekComparisonOut:
    """Units per category of a week next to the previous week and the same week last year."""
    comparison = dispatch_overview_service.compare_week(year=year, week=week, session=session)
    return WeekComparisonOut.model_validate(comparison)


@router.get("/{dispatch_id}", response_model=DispatchRead)
def get_dispatch(dispatch_id: int, session: Session = Depends(get_db)) -> DispatchRead:
    return DispatchRead.model_validate(
        dispatch_service.get_dispatch(dispatch_id, session)
    )


@router.get("/{dispatch_id}/matrix", response_model=DispatchMatrix)
def get_matrix(dispatch_id: int, session: Session = Depends(get_db)) -> DispatchMatrix:
    return DispatchMatrix.model_validate(
        dispatch_service.get_matrix(dispatch_id, session)
    )


@router.get("/{dispatch_id}/export.xlsx")
def export_dispatch_xlsx(dispatch_id: int, session: Session = Depends(get_db)) -> Response:
    """Download the dispatch day as a printable Excel file (summary + one pick list per fridge)."""
    dispatch = dispatch_service.get_dispatch(dispatch_id, session)
    document = dispatch_export_service.build_dispatch_xlsx(dispatch, session)
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
    )


@router.put("/{dispatch_id}/lines", response_model=DispatchRead)
def replace_lines(
    dispatch_id: int,
    body: DispatchLinesReplace,
    category_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> DispatchRead:
    dispatch_service.replace_lines(
        dispatch_id=dispatch_id,
        lines=[
            LineInput(
                fridge_id=line.fridge_id,
                product_id=line.product_id,
                qty=line.qty,
                source=line.source,
            )
            for line in body.lines
        ],
        category_id=category_id,
        user_id=None,
        session=session,
    )
    return DispatchRead.model_validate(
        dispatch_service.get_dispatch(dispatch_id, session)
    )


@router.post("/{dispatch_id}/apply-forecast", response_model=DispatchRead)
def apply_forecast(
    dispatch_id: int, session: Session = Depends(get_db)
) -> DispatchRead:
    dispatch_service.apply_forecast(
        dispatch_id=dispatch_id, user_id=None, session=session
    )
    return DispatchRead.model_validate(
        dispatch_service.get_dispatch(dispatch_id, session)
    )


@router.post("/{dispatch_id}/confirm", response_model=ConfirmResult)
def confirm_dispatch(
    dispatch_id: int,
    body: ConfirmRequest | None = None,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConfirmResult:
    force = body.force if body is not None else False
    dispatch, movements = dispatch_service.confirm_dispatch(
        dispatch_id=dispatch_id, force=force, user_id=current_user.id, session=session
    )
    return ConfirmResult(
        dispatch_id=dispatch.id,
        status=dispatch.status,
        movements_created=movements,
    )
