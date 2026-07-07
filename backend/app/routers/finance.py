"""Finance endpoints (R10/R11/R12): weekly P&L, monthly analysis, fridge GSV."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.finance import (
    FridgeReportRead,
    MonthlyAnalysisRead,
    WeeklyFinancialInputs,
    WeeklyPnlRead,
)
from app.services import finance_service, report_export_service
from app.services.orders_service import envelope

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])


@router.get("/weekly/{year}/{week}", response_model=WeeklyPnlRead)
@envelope
def get_weekly_pnl(
    year: int,
    week: int,
    db: Session = Depends(get_db),
) -> WeeklyPnlRead:
    return finance_service.get_weekly_pnl(db, year, week)


@router.put("/weekly/{year}/{week}", response_model=WeeklyPnlRead)
@envelope
def put_weekly_inputs(
    year: int,
    week: int,
    payload: WeeklyFinancialInputs,
    db: Session = Depends(get_db),
) -> WeeklyPnlRead:
    return finance_service.upsert_weekly_inputs(db, year, week, payload)


@router.get("/monthly", response_model=MonthlyAnalysisRead)
@envelope
def get_monthly_analysis(
    month: str = Query(..., description="YYYY-MM"),
    dimension: str = Query(..., description="client|supplier|category"),
    db: Session = Depends(get_db),
) -> MonthlyAnalysisRead:
    return finance_service.get_monthly_analysis(db, month, dimension)


@router.get("/fridge-report", response_model=FridgeReportRead)
@envelope
def get_fridge_report(
    fridge_id: int = Query(...),
    date_from: datetime.date = Query(..., alias="from"),
    date_to: datetime.date = Query(..., alias="to"),
    db: Session = Depends(get_db),
) -> FridgeReportRead:
    return finance_service.get_fridge_gsv_report(db, fridge_id, date_from, date_to)


@router.get("/fridge-report/export.xlsx")
@envelope
def export_fridge_report(
    fridge_id: int = Query(...),
    date_from: datetime.date = Query(..., alias="from"),
    date_to: datetime.date = Query(..., alias="to"),
    db: Session = Depends(get_db),
) -> Response:
    """Stream the fridge report as an ``.xlsx`` (summary on top, table below)."""
    data = finance_service.build_fridge_report(db, fridge_id, date_from, date_to)
    document = report_export_service.build_fridge_report_xlsx(data)
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.filename}"'
        },
    )
