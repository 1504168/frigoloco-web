"""Alert inbox endpoints (slide 12): list alerts and acknowledge them.

Alerts have no dedicated service module in this half's ownership, so the small
amount of persistence lives here; ``write_audit`` + commit keep the mutation
auditable and transactional in one place.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import AlertType
from app.models.operations import Alert
from app.schemas.alerts_settings import AlertRead
from app.schemas.orders import Page
from app.services.orders_service import (
    PageParams,
    envelope,
    get_page_params,
    not_found,
    write_audit,
)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=Page[AlertRead])
@envelope
def list_alerts(
    acknowledged: bool | None = None,
    status: str | None = None,
    alert_type: AlertType | None = None,
    page: PageParams = Depends(get_page_params),
    db: Session = Depends(get_db),
) -> Page[AlertRead]:
    conditions = []
    if acknowledged is True:
        conditions.append(Alert.status == "acknowledged")
    elif acknowledged is False:
        conditions.append(Alert.status == "open")
    if status is not None:
        conditions.append(Alert.status == status)
    if alert_type is not None:
        conditions.append(Alert.alert_type == alert_type)

    total = db.execute(
        select(func.count()).select_from(Alert).where(*conditions)
    ).scalar_one()
    rows = (
        db.execute(
            select(Alert)
            .where(*conditions)
            .order_by(Alert.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    return Page(
        items=[AlertRead.model_validate(a) for a in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.put("/{alert_id}/ack", response_model=AlertRead)
@envelope
def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
) -> AlertRead:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise not_found("alert", alert_id)

    before = {"status": alert.status}
    alert.status = "acknowledged"
    alert.acknowledged_at = datetime.datetime.now(datetime.timezone.utc)
    write_audit(
        db,
        action="acknowledge",
        entity="alert",
        entity_id=alert.id,
        before=before,
        after={"status": "acknowledged"},
    )
    db.commit()
    db.refresh(alert)
    return AlertRead.model_validate(alert)
