"""Restock verification endpoints (R9): run a reconciliation for a dispatch and
read stored verification runs. Prefix is ``/api/v1`` because the verify action
hangs off ``/dispatches/{id}`` while the reads live under ``/verifications``."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.orders import Page
from app.schemas.verifications import VerificationRead, VerificationSummary
from app.services import reconciliation_service
from app.services.orders_service import PageParams, envelope, get_page_params

router = APIRouter(prefix="/api/v1", tags=["verifications"])


@router.post(
    "/dispatches/{dispatch_id}/verify",
    response_model=VerificationRead,
    status_code=201,
)
@envelope
def verify_dispatch(
    dispatch_id: int,
    db: Session = Depends(get_db),
) -> VerificationRead:
    return reconciliation_service.reconcile_dispatch(db, dispatch_id)


@router.get("/verifications", response_model=Page[VerificationSummary])
@envelope
def list_verifications(
    dispatch_id: int | None = None,
    page: PageParams = Depends(get_page_params),
    db: Session = Depends(get_db),
) -> Page[VerificationSummary]:
    items, total = reconciliation_service.list_verifications(
        db, page, dispatch_id=dispatch_id
    )
    return Page(
        items=[VerificationSummary.model_validate(v) for v in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/verifications/{verification_id}", response_model=VerificationRead)
@envelope
def get_verification(
    verification_id: int,
    db: Session = Depends(get_db),
) -> VerificationRead:
    return reconciliation_service.get_verification(db, verification_id)
