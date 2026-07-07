"""Restock reconciliation (R9): diff RFID ADDED events against dispatched lines.

``diff = added(VALID, ADDED) − dispatched`` per fridge × product and per
category. UNRELIABLE tags are counted separately and excluded from the diff;
UNRECOGNISED tags are excluded entirely. Results persist to
``restock_verifications`` (+ lines); category totals are derived for the response.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import RestockAction, TagStatus
from app.models.events import RestockEvent
from app.models.master import Product
from app.models.operations import (
    Dispatch,
    DispatchLine,
    RestockVerification,
    RestockVerificationLine,
)
from app.schemas.verifications import (
    CategoryReconTotal,
    VerificationLineRead,
    VerificationRead,
)
from app.money import to_cents
from app.services.orders_service import PageParams, not_found, write_audit


@dataclass
class _PairAccumulator:
    dispatched_qty: int = 0
    added_qty: int = 0
    unreliable_qty: int = 0
    # Purchase price in cents (int from the DB); starts at 0.
    unit_purchase_price: int = 0
    category_id: int = 0


def _day_window(day: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.timezone.utc)
    return start, start + datetime.timedelta(days=1)


def reconcile_dispatch(session: Session, dispatch_id: int) -> VerificationRead:
    dispatch = session.get(Dispatch, dispatch_id)
    if dispatch is None:
        raise not_found("dispatch", dispatch_id)

    window_start, window_end = _day_window(dispatch.delivery_date)
    pairs: dict[tuple[int, int], _PairAccumulator] = defaultdict(_PairAccumulator)

    # Dispatched quantities (buy price = snapshot, else current product price).
    dispatched_rows = session.execute(
        select(
            DispatchLine.fridge_id,
            DispatchLine.product_id,
            func.sum(DispatchLine.qty),
            func.max(DispatchLine.unit_purchase_price),
            Product.purchase_price,
            Product.category_id,
        )
        .join(Product, Product.id == DispatchLine.product_id)
        .where(DispatchLine.dispatch_id == dispatch_id)
        .group_by(
            DispatchLine.fridge_id,
            DispatchLine.product_id,
            Product.purchase_price,
            Product.category_id,
        )
    ).all()
    for fridge_id, product_id, qty, snap_price, product_price, category_id in dispatched_rows:
        acc = pairs[(fridge_id, product_id)]
        acc.dispatched_qty += int(qty or 0)
        acc.unit_purchase_price = snap_price if snap_price is not None else product_price
        acc.category_id = category_id

    # RFID ADDED events in the delivery-day window, split by tag reliability.
    added_rows = session.execute(
        select(
            RestockEvent.fridge_id,
            RestockEvent.product_id,
            RestockEvent.tag_status,
            func.count(),
            Product.purchase_price,
            Product.category_id,
        )
        .join(Product, Product.id == RestockEvent.product_id)
        .where(
            RestockEvent.action == RestockAction.added,
            RestockEvent.occurred_at >= window_start,
            RestockEvent.occurred_at < window_end,
        )
        .group_by(
            RestockEvent.fridge_id,
            RestockEvent.product_id,
            RestockEvent.tag_status,
            Product.purchase_price,
            Product.category_id,
        )
    ).all()
    for fridge_id, product_id, tag_status, count, product_price, category_id in added_rows:
        if tag_status == TagStatus.unrecognised:
            continue  # excluded entirely (R9)
        acc = pairs[(fridge_id, product_id)]
        if not acc.unit_purchase_price:
            acc.unit_purchase_price = product_price
        if not acc.category_id:
            acc.category_id = category_id
        if tag_status == TagStatus.unreliable:
            acc.unreliable_qty += int(count)
        else:
            acc.added_qty += int(count)

    verification = RestockVerification(dispatch_id=dispatch_id)
    session.add(verification)
    session.flush()

    line_reads: list[VerificationLineRead] = []
    category_acc: dict[int, _PairAccumulator] = defaultdict(_PairAccumulator)
    value_by_cat: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for (fridge_id, product_id), acc in sorted(pairs.items()):
        diff_qty = acc.added_qty - acc.dispatched_qty
        diff_value = to_cents(Decimal(diff_qty) * Decimal(acc.unit_purchase_price))
        line = RestockVerificationLine(
            verification_id=verification.id,
            fridge_id=fridge_id,
            product_id=product_id,
            dispatched_qty=acc.dispatched_qty,
            added_qty=acc.added_qty,
            unreliable_qty=acc.unreliable_qty,
            diff_qty=diff_qty,
            diff_value=diff_value,
        )
        session.add(line)

        cat = category_acc[acc.category_id]
        cat.dispatched_qty += acc.dispatched_qty
        cat.added_qty += acc.added_qty
        cat.unreliable_qty += acc.unreliable_qty
        value_by_cat[acc.category_id] += Decimal(diff_qty) * Decimal(acc.unit_purchase_price)
        session.flush()
        line_reads.append(VerificationLineRead.model_validate(line))

    category_totals = [
        CategoryReconTotal(
            category_id=category_id,
            dispatched_qty=cat.dispatched_qty,
            added_qty=cat.added_qty,
            unreliable_qty=cat.unreliable_qty,
            diff_qty=cat.added_qty - cat.dispatched_qty,
            diff_value=to_cents(value_by_cat[category_id]),
        )
        for category_id, cat in sorted(category_acc.items())
    ]

    write_audit(
        session,
        action="reconcile",
        entity="dispatch",
        entity_id=dispatch_id,
        after={"verification_id": verification.id, "lines": len(line_reads)},
    )
    session.commit()

    return VerificationRead(
        id=verification.id,
        dispatch_id=dispatch_id,
        run_at=verification.run_at,
        lines=line_reads,
        category_totals=category_totals,
    )


def get_verification(session: Session, verification_id: int) -> VerificationRead:
    verification = session.get(RestockVerification, verification_id)
    if verification is None:
        raise not_found("verification", verification_id)

    lines = (
        session.execute(
            select(RestockVerificationLine, Product.category_id)
            .join(Product, Product.id == RestockVerificationLine.product_id)
            .where(RestockVerificationLine.verification_id == verification_id)
            .order_by(RestockVerificationLine.id)
        )
        .all()
    )
    line_reads = [VerificationLineRead.model_validate(row[0]) for row in lines]

    value_by_cat: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    qty_by_cat: dict[int, _PairAccumulator] = defaultdict(_PairAccumulator)
    for line, category_id in lines:
        cat = qty_by_cat[category_id]
        cat.dispatched_qty += line.dispatched_qty
        cat.added_qty += line.added_qty
        cat.unreliable_qty += line.unreliable_qty
        value_by_cat[category_id] += Decimal(line.diff_value)

    category_totals = [
        CategoryReconTotal(
            category_id=category_id,
            dispatched_qty=cat.dispatched_qty,
            added_qty=cat.added_qty,
            unreliable_qty=cat.unreliable_qty,
            diff_qty=cat.added_qty - cat.dispatched_qty,
            diff_value=to_cents(value_by_cat[category_id]),
        )
        for category_id, cat in sorted(qty_by_cat.items())
    ]

    return VerificationRead(
        id=verification.id,
        dispatch_id=verification.dispatch_id,
        run_at=verification.run_at,
        lines=line_reads,
        category_totals=category_totals,
    )


def list_verifications(
    session: Session, page: PageParams, dispatch_id: int | None = None
) -> tuple[list[RestockVerification], int]:
    conditions = []
    if dispatch_id is not None:
        conditions.append(RestockVerification.dispatch_id == dispatch_id)

    total = session.execute(
        select(func.count()).select_from(RestockVerification).where(*conditions)
    ).scalar_one()
    rows = (
        session.execute(
            select(RestockVerification)
            .where(*conditions)
            .order_by(RestockVerification.id.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    return list(rows), total
