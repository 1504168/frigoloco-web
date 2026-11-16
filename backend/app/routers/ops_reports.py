"""Operations report endpoints: restock report (#56) and loss report (#57), JSON and xlsx."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.ops_reports import LossReportRead, RestockReportRead
from app.services import ops_reports_service
from app.services.ops_reports_service import ReportScope
from app.services.orders_service import envelope
from app.services.report_export_service import ExcelDocument

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def read_report_scope(
    date_from: datetime.date = Query(..., alias="from"),
    date_to: datetime.date = Query(..., alias="to"),
    fridge_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
) -> ReportScope:
    return ReportScope(
        date_from=date_from,
        date_to=date_to,
        fridge_id=fridge_id,
        category_id=category_id,
    )


@router.get("/restock", response_model=RestockReportRead)
@envelope
def get_restock_report(
    scope: ReportScope = Depends(read_report_scope),
    db: Session = Depends(get_db),
) -> RestockReportRead:
    report_rows = ops_reports_service.load_restock_report(db, scope)
    return ops_reports_service.build_restock_report_read(report_rows, scope)


@router.get("/restock/export.xlsx")
@envelope
def export_restock_report(
    scope: ReportScope = Depends(read_report_scope),
    db: Session = Depends(get_db),
) -> Response:
    report_rows = ops_reports_service.load_restock_report(db, scope)
    document = ops_reports_service.build_restock_report_xlsx(report_rows, scope)
    return _attachment_response(document)


@router.get("/loss", response_model=LossReportRead)
@envelope
def get_loss_report(
    scope: ReportScope = Depends(read_report_scope),
    db: Session = Depends(get_db),
) -> LossReportRead:
    report_rows = ops_reports_service.load_loss_report(db, scope)
    return ops_reports_service.build_loss_report_read(report_rows, scope)


@router.get("/loss/export.xlsx")
@envelope
def export_loss_report(
    scope: ReportScope = Depends(read_report_scope),
    db: Session = Depends(get_db),
) -> Response:
    report_rows = ops_reports_service.load_loss_report(db, scope)
    document = ops_reports_service.build_loss_report_xlsx(report_rows, scope)
    return _attachment_response(document)


def _attachment_response(document: ExcelDocument) -> Response:
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
    )
