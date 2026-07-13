"""Stock ledger service (R6) plus the cross-cutting audit helper.

``record_audit`` lives here because ``stock_service`` sits at the bottom of the
ops service dependency graph (nothing in the ops slice is imported *by* it), so
every other service can import the helper without risking a circular import.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.engine import Row
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.enums import StockMovementType
from app.models.operations import AuditLog, StockMovement
from app.schemas.masters import PaginationParams, api_error

# PostgreSQL SQLSTATE raised by the stock non-negativity trigger.
_CHECK_VIOLATION = "23514"

# ---------------------------------------------------------------------------
# (iso_year, week_no, day_name) natural-key helpers - shared by the workflow
# pipeline (forecast / menu / dispatch all key on this triple). They live here
# because ``stock_service`` sits at the bottom of the ops dependency graph, so
# every workflow service can import them without a cycle. A calendar date maps
# bijectively to (iso_year, iso_week, iso_weekday), so ``delivery_date`` IS the
# natural key for the date-carrying tables.
# ---------------------------------------------------------------------------

# ISO weekday index (1=Monday) -> canonical day name.
WEEKDAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_DAY_NAME_TO_ISO_WEEKDAY: dict[str, int] = {
    name.lower(): index for index, name in enumerate(WEEKDAY_NAMES, start=1)
}


def day_name_for_date(day: datetime.date) -> str:
    """Canonical ISO weekday name (``'Monday'`` .. ``'Sunday'``) of ``day``."""
    return WEEKDAY_NAMES[day.isoweekday() - 1]


def resolve_delivery_date(year: int, week: int, day_name: str) -> datetime.date:
    """Map an ``(iso_year, week_no, day_name)`` key to its unique calendar date.

    Raises a 422 ``ApiException`` for an unknown day name or an ISO-invalid
    (year, week) - e.g. week 53 in a 52-week year.
    """
    weekday = _DAY_NAME_TO_ISO_WEEKDAY.get(day_name.strip().lower())
    if weekday is None:
        raise api_error(
            422,
            "validation_error",
            "day_name must be a weekday name (Monday..Sunday)",
            {"day_name": day_name},
        )
    try:
        return datetime.date.fromisocalendar(year, week, weekday)
    except ValueError as exc:
        raise api_error(
            422,
            "validation_error",
            "Invalid ISO (year, week) combination",
            {"year": year, "week": week, "day_name": day_name},
        ) from exc


def record_audit(
    session: Session,
    *,
    action: str,
    entity: str,
    entity_id: str | int | None,
    before: dict | None = None,
    after: dict | None = None,
    user_id: int | None = None,
) -> None:
    """Append an ``audit_log`` row (flushed with the enclosing transaction)."""
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=None if entity_id is None else str(entity_id),
            before_data=before,
            after_data=after,
        )
    )


def is_stock_non_negative_error(exc: DBAPIError) -> bool:
    """True when a DB error is the stock non-negativity trigger firing."""
    return getattr(getattr(exc, "orig", None), "pgcode", None) == _CHECK_VIOLATION


@dataclass(frozen=True)
class StockBalancesQuery:
    """Filters for the balances listing."""

    search: str | None = None


def list_balances(
    query: StockBalancesQuery, page: PaginationParams, session: Session
) -> tuple[list[Row], int]:
    """Return one page of ``v_stock_balances`` rows plus the total count."""
    where = ""
    params: dict[str, object] = {}
    if query.search:
        where = " WHERE product_code ILIKE :q OR product_name ILIKE :q"
        params["q"] = f"%{query.search}%"

    total = session.execute(
        text(f"SELECT count(*) FROM v_stock_balances{where}"), params
    ).scalar_one()

    rows = session.execute(
        text(
            "SELECT product_id, product_code, product_name, physical_qty, "
            "on_order_qty, available_qty FROM v_stock_balances"
            f"{where} ORDER BY product_code LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page.limit, "offset": page.offset},
    ).all()
    return list(rows), int(total)


def record_adjustment(
    *,
    product_id: int,
    qty: int,
    reason: str,
    user_id: int | None,
    session: Session,
    audit_action: str = "stock.adjust",
) -> StockMovement:
    """Insert a signed ``adjustment`` movement.

    The DB trigger is the source of truth for non-negativity: a rejected
    adjustment surfaces as a 409 ``stock_blocked``. ``audit_action`` lets the
    opening-stock flow record a distinct audit action while reusing this path.
    """
    movement = StockMovement(
        product_id=product_id,
        qty=qty,
        movement_type=StockMovementType.adjustment,
        reason=reason,
    )
    session.add(movement)
    record_audit(
        session,
        action=audit_action,
        entity="stock_movements",
        entity_id=None,
        after={"product_id": product_id, "qty": qty, "reason": reason},
        user_id=user_id,
    )
    try:
        session.flush()
    except DBAPIError as exc:
        session.rollback()
        if is_stock_non_negative_error(exc):
            balance = session.execute(
                text(
                    "SELECT physical_qty FROM v_stock_balances WHERE product_id = :p"
                ),
                {"p": product_id},
            ).scalar()
            raise api_error(
                409,
                "stock_blocked",
                "Adjustment would take stock below zero",
                [
                    {
                        "product_id": product_id,
                        "requested": qty,
                        "available": int(balance or 0),
                    }
                ],
            ) from exc
        raise
    session.commit()
    session.refresh(movement)
    return movement


def record_opening_stock(
    *,
    product_id: int,
    qty: int,
    reason: str,
    user_id: int | None,
    session: Session,
) -> StockMovement:
    """Record an opening-stock take as a positive ``adjustment`` movement (D2).

    Opening stock is a manual, reason-mandatory adjustment used to seed a
    product's initial physical balance (e.g. first stock take). It is the same
    append-only ledger path as :func:`record_adjustment`; only the audit action
    differs so opening takes are auditable separately from ad-hoc corrections.
    """
    if qty <= 0:
        raise api_error(
            422,
            "validation_error",
            "Opening stock qty must be positive",
            {"product_id": product_id, "qty": qty},
        )
    return record_adjustment(
        product_id=product_id,
        qty=qty,
        reason=reason,
        user_id=user_id,
        session=session,
        audit_action="stock.opening_stock",
    )


def list_movements(
    *,
    product_id: int | None,
    after_id: int | None,
    limit: int,
    session: Session,
) -> tuple[list[StockMovement], int | None]:
    """Keyset page of the movements ledger ordered by ascending id.

    Returns the rows and the ``next_after_id`` cursor (None when exhausted).
    """
    stmt = select(StockMovement)
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if after_id is not None:
        stmt = stmt.where(StockMovement.id > after_id)
    stmt = stmt.order_by(StockMovement.id).limit(limit + 1)

    rows = list(session.execute(stmt).scalars().all())
    next_after_id: int | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_after_id = rows[-1].id
    return rows, next_after_id
