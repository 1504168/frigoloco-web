"""Alert persistence: raise stock-blocked alerts without duplicates, shape alerts for the API."""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AlertType
from app.models.master import Product
from app.models.operations import Alert, Dispatch
from app.schemas.alerts_settings import (
    AlertDispatchRef,
    AlertRead,
    StockBlockedDetails,
    StockBlockedLine,
)
from app.services.stock_service import day_name_for_date

OPEN_STATUS = "open"
# Alerts stored before repeats were counted carry no count: they were raised once.
FIRST_OCCURRENCE = 1


@dataclass(frozen=True)
class OffendingLine:
    product_id: int
    requested: int
    available: int


def raise_stock_blocked_alert(
    session: Session,
    *,
    dispatch_id: int,
    offending_lines: list[OffendingLine],
) -> None:
    """Add a ``negative_blocked`` alert, or refresh the dispatch's open one (no commit)."""
    raised_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    line_payloads = [asdict(line) for line in offending_lines]
    open_alert = session.execute(
        select(Alert)
        .where(
            Alert.alert_type == AlertType.negative_blocked,
            Alert.status == OPEN_STATUS,
            Alert.payload["dispatch_id"].as_integer() == dispatch_id,
        )
        .order_by(Alert.created_at.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()

    if open_alert is None:
        session.add(
            Alert(
                alert_type=AlertType.negative_blocked,
                payload={
                    "dispatch_id": dispatch_id,
                    "offending_lines": line_payloads,
                    "occurrences": FIRST_OCCURRENCE,
                    "last_raised_at": raised_at,
                },
            )
        )
        return

    previous_occurrences = open_alert.payload.get("occurrences", FIRST_OCCURRENCE)
    # A new dict, not an in-place edit: the ORM does not see mutations inside JSONB.
    open_alert.payload = {
        **open_alert.payload,
        "offending_lines": line_payloads,
        "occurrences": previous_occurrences + 1,
        "last_raised_at": raised_at,
    }


def build_alert_reads(alerts: list[Alert], session: Session) -> list[AlertRead]:
    """API rows for ``alerts``; stock-blocked ones get product names and their dispatch."""
    stock_blocked_alerts = [
        alert for alert in alerts if alert.alert_type == AlertType.negative_blocked
    ]
    dispatch_ids = {alert.payload["dispatch_id"] for alert in stock_blocked_alerts}
    product_ids: set[int] = set()
    for alert in stock_blocked_alerts:
        for line in alert.payload["offending_lines"]:
            product_ids.add(line["product_id"])
    dispatch_refs = _load_dispatch_refs(dispatch_ids, session)
    product_names = _load_product_names(product_ids, session)

    alert_reads = []
    for alert in alerts:
        alert_read = AlertRead.model_validate(alert)
        if alert.alert_type == AlertType.negative_blocked:
            details = _build_stock_blocked_details(alert, dispatch_refs, product_names)
            alert_read = alert_read.model_copy(update={"stock_blocked": details})
        alert_reads.append(alert_read)
    return alert_reads


def _build_stock_blocked_details(
    alert: Alert,
    dispatch_refs: dict[int, AlertDispatchRef],
    product_names: dict[int, str],
) -> StockBlockedDetails:
    lines = []
    for line in alert.payload["offending_lines"]:
        product_id = line["product_id"]
        lines.append(
            StockBlockedLine(
                product_id=product_id,
                # The payload has no foreign key, so the product may be gone by now.
                product_name=product_names.get(product_id, f"Product #{product_id}"),
                requested=line["requested"],
                available=line["available"],
            )
        )
    return StockBlockedDetails(
        dispatch=dispatch_refs.get(alert.payload["dispatch_id"]),
        lines=lines,
        occurrences=alert.payload.get("occurrences", FIRST_OCCURRENCE),
        last_raised_at=alert.payload.get("last_raised_at", alert.created_at),
    )


def _load_dispatch_refs(
    dispatch_ids: set[int],
    session: Session,
) -> dict[int, AlertDispatchRef]:
    if not dispatch_ids:
        return {}
    dispatches = session.execute(
        select(Dispatch).where(Dispatch.id.in_(dispatch_ids))
    ).scalars()
    dispatch_refs = {}
    for dispatch in dispatches:
        dispatch_refs[dispatch.id] = AlertDispatchRef(
            dispatch_id=dispatch.id,
            delivery_date=dispatch.delivery_date,
            iso_year=dispatch.delivery_date.isocalendar().year,
            iso_week=dispatch.iso_week,
            day_name=day_name_for_date(dispatch.delivery_date),
        )
    return dispatch_refs


def _load_product_names(product_ids: set[int], session: Session) -> dict[int, str]:
    if not product_ids:
        return {}
    rows = session.execute(
        select(Product.id, Product.name).where(Product.id.in_(product_ids))
    ).all()
    return {row.id: row.name for row in rows}
