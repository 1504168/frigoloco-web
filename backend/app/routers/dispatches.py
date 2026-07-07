"""Dispatch batches: CRUD, matrix, line editing, apply-forecast, confirm."""

from __future__ import annotations

from fastapi import Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import DispatchStatus
from app.schemas.dispatches import (
    ConfirmRequest,
    ConfirmResult,
    DispatchCreate,
    DispatchLinesReplace,
    DispatchMatrix,
    DispatchRead,
    DispatchSaveRequest,
)
from app.schemas.masters import Page, PaginationParams, api_error, make_router, pagination
from app.services import dispatch_service
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
    session: Session = Depends(get_db),
) -> DispatchMatrix:
    """Preview dispatch lines seeded from the saved menu (not persisted)."""
    return DispatchMatrix.model_validate(
        dispatch_service.import_from_menu(
            year=year, week=week, day_name=day_name, session=session
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


@router.post("/create-individual", response_model=ConfirmResult)
def create_individual_dispatch(
    year: int = Query(..., ge=2020, le=2100),
    week: int = Query(..., ge=1, le=53),
    day_name: str = Query(...),
    force: bool = Query(default=False),
    session: Session = Depends(get_db),
) -> ConfirmResult:
    """Create the individual dispatch for the key: flip to dispatched, snapshot
    prices, write the negative stock movements (the ONLY stock-writing path)."""
    dispatch, movements = dispatch_service.create_individual_by_key(
        year=year, week=week, day_name=day_name, force=force, user_id=None, session=session
    )
    return ConfirmResult(
        dispatch_id=dispatch.id,
        status=dispatch.status,
        movements_created=movements,
    )


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
) -> ConfirmResult:
    force = body.force if body is not None else False
    dispatch, movements = dispatch_service.confirm_dispatch(
        dispatch_id=dispatch_id, force=force, user_id=None, session=session
    )
    return ConfirmResult(
        dispatch_id=dispatch.id,
        status=dispatch.status,
        movements_created=movements,
    )
