"""Purchase-order domain logic (R4/R5) plus the cross-cutting service/router
infrastructure shared across the supply + finance half of the API.

The infrastructure block at the top (``ApiError``, the ``envelope`` decorator,
``PageParams``, ``write_audit``, money rounding) is imported by the sibling
finance/reconciliation services and by every router in this half, so it lives in
one place rather than being duplicated. ``orders_service`` is the natural home
because purchase orders are the first mutation-heavy domain of this half.
"""

from __future__ import annotations

import datetime
import inspect
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from functools import wraps
from typing import Any, Callable, get_type_hints

from fastapi import Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import bindparam, func, or_, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import (
    PoDiscrepancyKind,
    PoDiscrepancyReason,
    PoStatus,
    StockMovementType,
)
from app.models.master import Product, Supplier, User
from app.models.operations import (
    AuditLog,
    Dispatch,
    DispatchLine,
    PurchaseOrder,
    PurchaseOrderDiscrepancy,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    StockMovement,
)
from app.models.planning import MenuLine, WeeklyMenu
from app.money import to_cents
from app.schemas.orders import (
    MenuOrderPlan,
    MenuOrderPlanLine,
    MenuOrderPlanSupplier,
    PoDiscrepancyRead,
    PoHistoryAction,
    PoHistoryEvent,
    PoHistoryLine,
    PoLineCreate,
    PoReceiptLineRead,
    PoReceiptRead,
    PurchaseOrderCreate,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
    StockMovementRead,
)
from app.services.stock_service import resolve_delivery_date

# ===========================================================================
# Shared infrastructure (imported across the supply + finance half)
# ===========================================================================


class ApiError(Exception):
    """Business/HTTP error rendered as the standard ``{"error": {...}}`` body."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def to_response(self) -> JSONResponse:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return JSONResponse(status_code=self.status_code, content={"error": body})


def not_found(entity: str, entity_id: Any) -> ApiError:
    return ApiError(404, "not_found", f"{entity} {entity_id} not found")


def envelope(func: Callable) -> Callable:
    """Wrap a sync router endpoint so any ``ApiError`` becomes the error envelope.

    ``functools.wraps`` preserves ``__wrapped__`` so FastAPI still resolves the
    endpoint's dependencies and query params from the original signature.

    Routers use ``from __future__ import annotations`` (PEP 563), so their
    endpoint annotations are *strings*. FastAPI resolves those strings against
    the callable's ``__globals__`` - which, for the wrapper, is THIS module, not
    the router module. Body-model classes (e.g. ``WeeklyFinancialInputs``) live
    in the router's namespace and are absent here, so the string would fail to
    resolve and FastAPI would misclassify the body param as a query param. We
    therefore pre-resolve the wrapped function's hints against its OWN module and
    pin a fully-typed ``__signature__`` onto the wrapper so FastAPI sees the real
    classes regardless of Python version / PEP 563.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ApiError as exc:
            return exc.to_response()

    try:
        hints = get_type_hints(func)
        signature = inspect.signature(func)
        wrapper.__signature__ = signature.replace(  # type: ignore[attr-defined]
            parameters=[
                param.replace(annotation=hints.get(param.name, param.annotation))
                for param in signature.parameters.values()
            ]
        )
    except Exception:  # pragma: no cover - defensive: never break a valid route
        pass

    return wrapper


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


def get_page_params(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PageParams:
    """FastAPI dependency yielding validated pagination parameters."""
    return PageParams(limit=limit, offset=offset)


def write_audit(
    session: Session,
    *,
    action: str,
    entity: str,
    entity_id: str | int | None,
    before: dict | None = None,
    after: dict | None = None,
    user_id: int | None = None,
) -> None:
    """Append one ``audit_log`` row for a mutation (no auth yet → ``user_id`` None)."""
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            before_data=jsonable_encoder(before) if before is not None else None,
            after_data=jsonable_encoder(after) if after is not None else None,
        )
    )


def is_stock_non_negative_violation(exc: Exception) -> bool:
    """True when a DB error is the non-negativity trigger's check_violation."""
    orig = getattr(exc, "orig", None)
    pgcode = getattr(orig, "pgcode", None)
    if pgcode == "23514":  # check_violation
        return True
    return "non-negativity" in str(exc).lower()


# ===========================================================================
# Internal payloads (frozen dataclasses per project convention)
# ===========================================================================


@dataclass(frozen=True)
class PoTotals:
    # Integer minor units (cents).
    ex_vat: int
    vat: int
    incl_vat: int


@dataclass(frozen=True)
class PricedPoLine:
    product_id: int
    qty: int
    unit_price_cents: int
    vat_rate: Decimal


@dataclass(frozen=True)
class ReceiptLine:
    po_line_id: int
    qty_received: int


@dataclass(frozen=True)
class ShortLineNote:
    """Optional reason and comment for one short line when a PO is closed short."""

    po_line_id: int
    reason: PoDiscrepancyReason | None
    comment: str | None


@dataclass(frozen=True)
class PoLineProduct:
    code: str
    name: str
    qty_ordered: int


@dataclass(frozen=True)
class PoHistorySources:
    """Everything the history builders read besides the audit row itself."""

    products_by_line: dict[int, PoLineProduct]
    shortfalls: list[PurchaseOrderDiscrepancy]
    over_receipts_by_receipt: dict[int, list[PurchaseOrderDiscrepancy]]


AUDIT_ACTION_TO_HISTORY_ACTION: dict[str, PoHistoryAction] = {
    "create": "created",
    "update": "edited",
    "receive": "received",
    "close_short": "closed_short",
    "cancel": "cancelled",
}

# Discrepancy log days are Brussels calendar days, like the rest of the app.
LOCAL_TIMEZONE_NAME = "Europe/Brussels"

EDITABLE_FIELD_LABELS = {
    "expected_delivery_date": "Expected delivery",
    "delivery_address": "Deliver to",
    "comment": "Comment",
}

DISCREPANCY_REASON_LABELS = {
    PoDiscrepancyReason.missing: "missing",
    PoDiscrepancyReason.damaged: "damaged",
    PoDiscrepancyReason.wrong_product: "wrong product",
    PoDiscrepancyReason.other: "other",
}


# ===========================================================================
# Pure math (parity-testable without a database)
# ===========================================================================


def compute_line_totals(
    unit_price_cents: int, qty: int, vat_rate: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """One PO line's ex-VAT, VAT and incl-VAT amounts in CENTS (unrounded, R5).

    ``unit_price_cents`` is integer minor units; VAT is a fraction, so the VAT
    and incl-VAT parts carry fractional cents until the caller rounds them.
    """
    base = Decimal(unit_price_cents) * Decimal(qty)
    vat = base * Decimal(vat_rate)
    return base, vat, base + vat


def compute_po_totals(lines: list[PricedPoLine]) -> PoTotals:
    """Accumulate ex-VAT / VAT / incl-VAT separately in cents, then round each (R5).

    Parity anchor (order 2026-00360): 239.36 / 14.36 / 253.72 euros, i.e.
    23936 / 1436 / 25372 cents.
    """
    ex_total = Decimal("0")
    vat_total = Decimal("0")
    incl_total = Decimal("0")
    for line in lines:
        base, vat, incl = compute_line_totals(line.unit_price_cents, line.qty, line.vat_rate)
        ex_total += base
        vat_total += vat
        incl_total += incl
    return PoTotals(
        ex_vat=to_cents(ex_total), vat=to_cents(vat_total), incl_vat=to_cents(incl_total)
    )


# ===========================================================================
# Read-model assembly
# ===========================================================================


def _line_to_read(
    line: PurchaseOrderLine, product_code: str, product_name: str
) -> PurchaseOrderLineRead:
    base, vat, incl = compute_line_totals(line.unit_price, line.qty_ordered, line.vat_rate)
    return PurchaseOrderLineRead(
        id=line.id,
        product_id=line.product_id,
        product_code=product_code,
        product_name=product_name,
        qty_ordered=line.qty_ordered,
        qty_received=line.qty_received,
        unit_price=line.unit_price,
        vat_rate=line.vat_rate,
        line_ex_vat=to_cents(base),
        line_vat=to_cents(vat),
        line_incl_vat=to_cents(incl),
    )


def _po_to_read(session: Session, po: PurchaseOrder) -> PurchaseOrderRead:
    # Join products so each line carries code + name (PO detail UI shows those,
    # not the raw product #id).
    rows = session.execute(
        select(PurchaseOrderLine, Product.code, Product.name)
        .join(Product, Product.id == PurchaseOrderLine.product_id)
        .where(PurchaseOrderLine.po_id == po.id)
        .order_by(PurchaseOrderLine.id)
    ).all()
    return PurchaseOrderRead(
        id=po.id,
        order_no=po.order_no,
        supplier_id=po.supplier_id,
        status=po.status,
        order_date=po.order_date,
        expected_delivery_date=po.expected_delivery_date,
        delivery_address=po.delivery_address,
        comment=po.comment,
        total_ex_vat=po.total_ex_vat,
        total_vat=po.total_vat,
        total_incl_vat=po.total_incl_vat,
        created_at=po.created_at,
        lines=[
            _line_to_read(line, code, name) for line, code, name in rows
        ],
    )


def _get_po_or_404(session: Session, po_id: int) -> PurchaseOrder:
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise not_found("purchase_order", po_id)
    return po


# ===========================================================================
# Purchase-order operations
# ===========================================================================


def list_purchase_orders(
    session: Session,
    page: PageParams,
    status: PoStatus | None = None,
    supplier_id: int | None = None,
    delivery_from: datetime.date | None = None,
    delivery_to: datetime.date | None = None,
    search: str | None = None,
) -> tuple[list[PurchaseOrderRead], int]:
    conditions = []
    if status is not None:
        conditions.append(PurchaseOrder.status == status)
    if supplier_id is not None:
        conditions.append(PurchaseOrder.supplier_id == supplier_id)
    # Warehouse view: filter by expected delivery date (what is arriving when).
    if delivery_from is not None:
        conditions.append(PurchaseOrder.expected_delivery_date >= delivery_from)
    if delivery_to is not None:
        conditions.append(PurchaseOrder.expected_delivery_date <= delivery_to)
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(
                PurchaseOrder.order_no.ilike(pattern),
                Supplier.name.ilike(pattern),
            )
        )

    total_count = session.execute(
        select(func.count())
        .select_from(PurchaseOrder)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(*conditions)
    ).scalar_one()

    rows = (
        session.execute(
            select(PurchaseOrder)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .where(*conditions)
            .order_by(PurchaseOrder.id.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    return [_po_to_read(session, po) for po in rows], total_count


def get_purchase_order(session: Session, po_id: int) -> PurchaseOrderRead:
    return _po_to_read(session, _get_po_or_404(session, po_id))


def create_purchase_order(
    session: Session,
    payload: PurchaseOrderCreate,
    user_id: int | None = None,
) -> PurchaseOrderRead:
    today = datetime.date.today()
    if payload.order_date < today:
        raise ApiError(
            422, "unprocessable_entity", "order_date cannot be in the past"
        )
    if payload.expected_delivery_date < payload.order_date:
        raise ApiError(
            422,
            "unprocessable_entity",
            "expected_delivery_date cannot precede order_date",
        )

    priced_lines = _price_lines_from_catalogue(session, payload)
    order_no = session.execute(select(func.next_order_no())).scalar_one()
    totals = compute_po_totals(priced_lines)

    po = PurchaseOrder(
        order_no=order_no,
        supplier_id=payload.supplier_id,
        status=PoStatus.pending,
        order_date=payload.order_date,
        expected_delivery_date=payload.expected_delivery_date,
        delivery_address=payload.delivery_address,
        comment=payload.comment,
        total_ex_vat=totals.ex_vat,
        total_vat=totals.vat,
        total_incl_vat=totals.incl_vat,
        created_by=user_id,
    )
    session.add(po)
    session.flush()

    for line in priced_lines:
        session.add(
            PurchaseOrderLine(
                po_id=po.id,
                product_id=line.product_id,
                qty_ordered=line.qty,
                qty_received=0,
                unit_price=line.unit_price_cents,
                vat_rate=line.vat_rate,
            )
        )
    session.flush()

    write_audit(
        session,
        action="create",
        entity="purchase_order",
        entity_id=po.id,
        after={"order_no": order_no, "supplier_id": payload.supplier_id},
        user_id=user_id,
    )
    session.commit()
    session.refresh(po)
    return _po_to_read(session, po)


def update_purchase_order(
    session: Session,
    po_id: int,
    payload: PurchaseOrderUpdate,
    user_id: int | None,
) -> PurchaseOrderRead:
    po = _get_po_or_404(session, po_id)
    if po.status != PoStatus.pending:
        raise ApiError(
            409, "conflict", "only pending purchase orders can be edited"
        )
    before = {
        "expected_delivery_date": po.expected_delivery_date.isoformat(),
        "delivery_address": po.delivery_address,
        "comment": po.comment,
    }
    if payload.expected_delivery_date is not None:
        if payload.expected_delivery_date < po.order_date:
            raise ApiError(
                422,
                "unprocessable_entity",
                "expected_delivery_date cannot precede order_date",
            )
        po.expected_delivery_date = payload.expected_delivery_date
    if payload.delivery_address is not None:
        po.delivery_address = payload.delivery_address
    if payload.comment is not None:
        po.comment = payload.comment

    write_audit(
        session,
        action="update",
        entity="purchase_order",
        entity_id=po.id,
        before=before,
        after=payload.model_dump(exclude_none=True, mode="json"),
        user_id=user_id,
    )
    session.commit()
    session.refresh(po)
    return _po_to_read(session, po)


def receive_purchase_order(
    session: Session,
    po_id: int,
    receipts: list[ReceiptLine],
    acknowledge_over_receipt: bool,
    comment: str | None,
    user_id: int | None,
) -> tuple[PurchaseOrderRead, list[StockMovementRead]]:
    po = _get_po_or_404(session, po_id)
    if po.status != PoStatus.pending:
        raise ApiError(
            409, "conflict", f"purchase order is {po.status.value}, not pending"
        )

    lines = _load_po_lines(session, po.id)

    over: list[dict] = []
    for receipt in receipts:
        line = lines.get(receipt.po_line_id)
        if line is None:
            raise ApiError(
                422,
                "unprocessable_entity",
                f"po_line {receipt.po_line_id} does not belong to this order",
            )
        projected = line.qty_received + receipt.qty_received
        if projected > line.qty_ordered:
            over.append(
                {
                    "po_line_id": line.id,
                    "qty_ordered": line.qty_ordered,
                    "qty_received": projected,
                }
            )
    if over and not acknowledge_over_receipt:
        raise ApiError(
            409,
            "over_receipt",
            "one or more lines exceed the ordered quantity; set acknowledge_over_receipt=true",
            details=over,
        )

    receipt_event = PurchaseOrderReceipt(
        po_id=po.id,
        comment=comment or None,
        created_by=user_id,
    )
    session.add(receipt_event)
    session.flush()

    movements: list[StockMovement] = []
    for receipt in receipts:
        line = lines[receipt.po_line_id]
        units_before_receipt = line.qty_received
        line.qty_received += receipt.qty_received
        over_receipt = _over_receipt_discrepancy(
            line,
            units_before_receipt=units_before_receipt,
            receipt_id=receipt_event.id,
            user_id=user_id,
        )
        if over_receipt is not None:
            session.add(over_receipt)
        movement = StockMovement(
            product_id=line.product_id,
            qty=receipt.qty_received,
            movement_type=StockMovementType.po_receipt,
            po_line_id=line.id,
            receipt_id=receipt_event.id,
            created_by=user_id,
        )
        session.add(movement)
        movements.append(movement)
    session.flush()

    if all(line.qty_received >= line.qty_ordered for line in lines.values()):
        po.status = PoStatus.received

    write_audit(
        session,
        action="receive",
        entity="purchase_order",
        entity_id=po.id,
        after={
            "received": [r.__dict__ for r in receipts],
            "status": po.status.value,
            "receipt_id": receipt_event.id,
            "comment": receipt_event.comment,
        },
        user_id=user_id,
    )
    session.commit()
    session.refresh(po)
    movement_reads = [StockMovementRead.model_validate(m) for m in movements]
    return _po_to_read(session, po), movement_reads


def list_purchase_order_receipts(session: Session, po_id: int) -> list[PoReceiptRead]:
    """Every receive action of a purchase order, newest first, with its received lines."""
    _get_po_or_404(session, po_id)
    receipt_rows = session.execute(
        select(PurchaseOrderReceipt, User.full_name)
        .outerjoin(User, User.id == PurchaseOrderReceipt.created_by)
        .where(PurchaseOrderReceipt.po_id == po_id)
        .order_by(PurchaseOrderReceipt.created_at.desc(), PurchaseOrderReceipt.id.desc())
    ).all()
    receipt_ids = [receipt.id for receipt, _ in receipt_rows]
    line_rows = session.execute(
        select(StockMovement.receipt_id, Product.code, Product.name, StockMovement.qty)
        .join(Product, Product.id == StockMovement.product_id)
        .where(StockMovement.receipt_id.in_(receipt_ids))
        .order_by(StockMovement.id)
    ).all()

    lines_by_receipt: dict[int, list[PoReceiptLineRead]] = defaultdict(list)
    for receipt_id, product_code, product_name, qty in line_rows:
        lines_by_receipt[receipt_id].append(
            PoReceiptLineRead(
                product_code=product_code,
                product_name=product_name,
                qty_received=qty,
            )
        )
    return [
        PoReceiptRead(
            id=receipt.id,
            comment=receipt.comment,
            created_by_name=created_by_name,
            created_at=receipt.created_at,
            lines=lines_by_receipt[receipt.id],
        )
        for receipt, created_by_name in receipt_rows
    ]


def cancel_purchase_order(
    session: Session,
    po_id: int,
    user_id: int | None,
) -> tuple[PurchaseOrderRead, PoStatus, list[StockMovementRead]]:
    po = _get_po_or_404(session, po_id)
    previous = po.status
    if po.status == PoStatus.cancelled:
        raise ApiError(409, "conflict", "purchase order is already cancelled")

    # A partly received PO is still pending, so reversal keys on received qty, not status.
    received_lines = (
        session.execute(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.po_id == po.id,
                PurchaseOrderLine.qty_received > 0,
            )
        )
        .scalars()
        .all()
    )
    reversals: list[StockMovement] = []
    for line in received_lines:
        movement = StockMovement(
            product_id=line.product_id,
            qty=-line.qty_received,
            movement_type=StockMovementType.cancellation_reversal,
            po_line_id=line.id,
            created_by=user_id,
        )
        session.add(movement)
        reversals.append(movement)
    try:
        session.flush()
    except (IntegrityError, DBAPIError) as exc:
        session.rollback()
        if is_stock_non_negative_violation(exc):
            raise ApiError(
                409,
                "cancel_blocked",
                "received stock has already been dispatched; cancellation refused",
            ) from exc
        raise
    reversal_reads = [StockMovementRead.model_validate(m) for m in reversals]

    po.status = PoStatus.cancelled
    write_audit(
        session,
        action="cancel",
        entity="purchase_order",
        entity_id=po.id,
        before={"status": previous.value},
        after={
            "status": PoStatus.cancelled.value,
            "reversed": [
                {"po_line_id": line.id, "qty": line.qty_received} for line in received_lines
            ],
        },
        user_id=user_id,
    )
    session.commit()
    session.refresh(po)
    return _po_to_read(session, po), previous, reversal_reads


def draft_purchase_orders_from_dispatch(
    session: Session, dispatch_id: int
) -> list[PurchaseOrderRead]:
    """Aggregate a dispatch's lines into one pending PO per supplier (R4).

    Products with no supplier are skipped; quantities are aggregated per
    (supplier, product) at the product's current purchase price and VAT rate.
    """
    dispatch = session.get(Dispatch, dispatch_id)
    if dispatch is None:
        raise not_found("dispatch", dispatch_id)

    rows = session.execute(
        select(
            Product.supplier_id,
            DispatchLine.product_id,
            DispatchLine.qty,
        )
        .join(Product, Product.id == DispatchLine.product_id)
        .where(DispatchLine.dispatch_id == dispatch_id)
    ).all()

    per_supplier: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for supplier_id, product_id, qty in rows:
        if supplier_id is None or qty <= 0:
            continue
        per_supplier[supplier_id][product_id] += qty

    today = datetime.date.today()
    expected = max(today, dispatch.delivery_date)
    created: list[PurchaseOrderRead] = []
    for supplier_id, product_quantities in per_supplier.items():
        line_payloads = [
            PoLineCreate(product_id=product_id, qty=qty)
            for product_id, qty in product_quantities.items()
        ]
        draft = PurchaseOrderCreate(
            supplier_id=supplier_id,
            order_date=today,
            expected_delivery_date=expected,
            delivery_address=None,
            comment=f"Drafted from dispatch {dispatch_id}",
            lines=line_payloads,
        )
        created.append(create_purchase_order(session, draft))
    return created


# ===========================================================================
# D2 - draft a purchase order from a SAVED menu (per supplier)
# ===========================================================================
# APPEND-ONLY (WORKORDER D2 ownership contract): the menus router owns the
# (iso_year, week_no, day_name) menu key and passes the already-aggregated
# per-product quantities in; this function only turns them into a supplier PO,
# reusing create_purchase_order. It touches no menu tables.


def draft_from_menu(
    session: Session,
    *,
    supplier_id: int,
    product_quantities: dict[int, int],
    expected_delivery_date: datetime.date,
    comment: str,
) -> PurchaseOrderRead:
    """Create one pending PO for ``supplier_id`` from menu product quantities (R4/D2).

    Mirrors the Excel "Order details (va chercher dans le menu)" button: line
    quantities come from the saved menu; create_purchase_order prices them from
    the catalogue. Raises 422 when the quantity set is empty (no menu lines for
    this supplier).
    """
    ordered = {pid: qty for pid, qty in product_quantities.items() if qty > 0}
    if not ordered:
        raise ApiError(
            422,
            "unprocessable_entity",
            "No menu quantities for this supplier",
        )

    line_payloads = [
        PoLineCreate(product_id=product_id, qty=qty)
        for product_id, qty in ordered.items()
    ]
    today = datetime.date.today()
    draft = PurchaseOrderCreate(
        supplier_id=supplier_id,
        order_date=today,
        expected_delivery_date=max(today, expected_delivery_date),
        delivery_address=None,
        comment=comment,
        lines=line_payloads,
    )
    return create_purchase_order(session, draft)


def close_purchase_order_short(
    session: Session,
    po_id: int,
    notes: list[ShortLineNote],
    user_id: int | None,
) -> PurchaseOrderRead:
    """Close a pending PO with the units received so far, logging each line's shortfall.

    The open remainder stops counting as on order (v_stock_balances counts pending POs only).
    """
    po = _get_po_or_404(session, po_id)
    if po.status != PoStatus.pending:
        raise ApiError(
            409, "conflict", f"purchase order is {po.status.value}, not pending"
        )
    lines = _load_po_lines(session, po.id)
    notes_by_line = {note.po_line_id: note for note in notes}
    for po_line_id in notes_by_line:
        if po_line_id not in lines:
            raise ApiError(
                422,
                "unprocessable_entity",
                f"po_line {po_line_id} does not belong to this order",
            )

    short_lines = [line for line in lines.values() if line.qty_received < line.qty_ordered]
    for line in short_lines:
        note = notes_by_line.get(line.id)
        session.add(
            PurchaseOrderDiscrepancy(
                po_id=po.id,
                po_line_id=line.id,
                kind=PoDiscrepancyKind.short,
                qty_ordered=line.qty_ordered,
                qty_received=line.qty_received,
                qty_difference=line.qty_ordered - line.qty_received,
                reason=note.reason if note else None,
                comment=note.comment if note else None,
                created_by=user_id,
            )
        )

    po.status = PoStatus.closed_short
    write_audit(
        session,
        action="close_short",
        entity="purchase_order",
        entity_id=po.id,
        before={"status": PoStatus.pending.value},
        after={"status": PoStatus.closed_short.value, "short_line_count": len(short_lines)},
        user_id=user_id,
    )
    session.commit()
    session.refresh(po)
    return _po_to_read(session, po)


def list_purchase_order_discrepancies(
    session: Session,
    page: PageParams,
    kind: PoDiscrepancyKind | None = None,
    supplier_id: int | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[list[PoDiscrepancyRead], int]:
    """The "Not received" log: shortfalls and over-receipts across all POs, newest first."""
    conditions = []
    if kind is not None:
        conditions.append(PurchaseOrderDiscrepancy.kind == kind)
    if supplier_id is not None:
        conditions.append(PurchaseOrder.supplier_id == supplier_id)
    logged_on = func.date(func.timezone(LOCAL_TIMEZONE_NAME, PurchaseOrderDiscrepancy.created_at))
    if date_from is not None:
        conditions.append(logged_on >= date_from)
    if date_to is not None:
        conditions.append(logged_on <= date_to)

    total_count = session.execute(
        select(func.count())
        .select_from(PurchaseOrderDiscrepancy)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderDiscrepancy.po_id)
        .where(*conditions)
    ).scalar_one()

    rows = session.execute(
        select(
            PurchaseOrderDiscrepancy,
            PurchaseOrder.order_no,
            PurchaseOrder.supplier_id,
            Supplier.name,
            Product.code,
            Product.name,
            User.full_name,
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderDiscrepancy.po_id)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .join(PurchaseOrderLine, PurchaseOrderLine.id == PurchaseOrderDiscrepancy.po_line_id)
        .join(Product, Product.id == PurchaseOrderLine.product_id)
        .outerjoin(User, User.id == PurchaseOrderDiscrepancy.created_by)
        .where(*conditions)
        .order_by(PurchaseOrderDiscrepancy.created_at.desc(), PurchaseOrderDiscrepancy.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    discrepancies = [
        PoDiscrepancyRead(
            id=discrepancy.id,
            po_id=discrepancy.po_id,
            order_no=order_no,
            supplier_id=po_supplier_id,
            supplier_name=supplier_name,
            product_code=product_code,
            product_name=product_name,
            kind=discrepancy.kind,
            qty_ordered=discrepancy.qty_ordered,
            qty_received=discrepancy.qty_received,
            qty_difference=discrepancy.qty_difference,
            reason=discrepancy.reason,
            comment=discrepancy.comment,
            created_by_name=created_by_name,
            created_at=discrepancy.created_at,
        )
        for (
            discrepancy,
            order_no,
            po_supplier_id,
            supplier_name,
            product_code,
            product_name,
            created_by_name,
        ) in rows
    ]
    return discrepancies, total_count


def get_purchase_order_history(session: Session, po_id: int) -> list[PoHistoryEvent]:
    """Activity timeline of one PO, newest first: created, edited, receipts, short-close, cancel."""
    po = _get_po_or_404(session, po_id)
    audit_rows = session.execute(
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(
            AuditLog.entity == "purchase_order",
            AuditLog.entity_id == str(po.id),
        )
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
    ).all()
    sources = _load_history_sources(session, po.id)

    events: list[PoHistoryEvent] = []
    for audit, user_name in audit_rows:
        history_action = AUDIT_ACTION_TO_HISTORY_ACTION.get(audit.action)
        if history_action is None:
            continue
        events.append(
            PoHistoryEvent(
                action=history_action,
                at=audit.at,
                user_name=user_name,
                comment=_history_comment(audit),
                lines=_history_lines(history_action, audit, sources),
            )
        )

    has_created_event = any(event.action == "created" for event in events)
    if not has_created_event:
        # Orders imported from the Excel history have no "create" audit row.
        events.append(
            PoHistoryEvent(
                action="created",
                at=po.created_at,
                user_name=None,
                comment=None,
                lines=_ordered_history_lines(sources),
            )
        )
    return events


def compute_to_order_qty(need_qty: int, in_stock_qty: int, on_order_qty: int) -> int:
    """Units still to order once warehouse stock and open orders are used; never below 0."""
    return max(need_qty - in_stock_qty - on_order_qty, 0)


def build_menu_order_plan(
    session: Session,
    *,
    year: int,
    week: int,
    day_names: list[str],
) -> MenuOrderPlan:
    """Propose one PO per supplier from the saved menus of the chosen delivery days.

    need = menu units for those days; to order = need - warehouse stock - already on order.
    """
    delivery_dates = [resolve_delivery_date(year, week, day_name) for day_name in day_names]
    saved_day_names = set(
        session.execute(
            select(WeeklyMenu.day_name).where(
                WeeklyMenu.year == year,
                WeeklyMenu.iso_week == week,
                WeeklyMenu.day_name.in_(day_names),
            )
        ).scalars()
    )
    days_without_menu = [day_name for day_name in day_names if day_name not in saved_day_names]

    need_by_product = _menu_need_by_product(session, year=year, week=week, day_names=day_names)
    plan_lines_by_supplier = _plan_lines_by_supplier(session, need_by_product)
    lines_without_supplier = plan_lines_by_supplier.pop(None, [])

    supplier_names = _supplier_names(session, list(plan_lines_by_supplier))
    suppliers = [
        MenuOrderPlanSupplier(
            supplier_id=supplier_id,
            supplier_name=supplier_names[supplier_id],
            lines=plan_lines,
        )
        for supplier_id, plan_lines in plan_lines_by_supplier.items()
    ]
    suppliers.sort(key=_supplier_sort_key)

    today = datetime.date.today()
    return MenuOrderPlan(
        year=year,
        week=week,
        day_names=day_names,
        days_without_menu=days_without_menu,
        expected_delivery_date=max(today, min(delivery_dates)),
        suppliers=suppliers,
        lines_without_supplier=lines_without_supplier,
    )


def _price_lines_from_catalogue(
    session: Session,
    payload: PurchaseOrderCreate,
) -> list[PricedPoLine]:
    """Price each line from the product catalogue; the client never sets price or VAT."""
    product_ids = [line.product_id for line in payload.lines]
    products_by_id = {
        product.id: product
        for product in session.execute(select(Product).where(Product.id.in_(product_ids)))
        .scalars()
        .all()
    }
    priced_lines: list[PricedPoLine] = []
    for line in payload.lines:
        product = products_by_id.get(line.product_id)
        if product is None:
            raise ApiError(
                422,
                "unprocessable_entity",
                f"product {line.product_id} does not exist",
            )
        if product.supplier_id != payload.supplier_id:
            raise ApiError(
                422,
                "unprocessable_entity",
                f"product {product.code} is not supplied by this supplier",
            )
        priced_lines.append(
            PricedPoLine(
                product_id=product.id,
                qty=line.qty,
                unit_price_cents=product.purchase_price,
                vat_rate=product.vat_rate,
            )
        )
    return priced_lines


def _load_po_lines(session: Session, po_id: int) -> dict[int, PurchaseOrderLine]:
    po_lines = session.execute(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)
    ).scalars()
    return {line.id: line for line in po_lines}


def _over_receipt_discrepancy(
    line: PurchaseOrderLine,
    *,
    units_before_receipt: int,
    receipt_id: int,
    user_id: int | None,
) -> PurchaseOrderDiscrepancy | None:
    """The excess this receipt added beyond the ordered quantity, or None when it added none."""
    excess_before = max(units_before_receipt - line.qty_ordered, 0)
    excess_after = max(line.qty_received - line.qty_ordered, 0)
    excess_added = excess_after - excess_before
    if excess_added <= 0:
        return None
    return PurchaseOrderDiscrepancy(
        po_id=line.po_id,
        po_line_id=line.id,
        receipt_id=receipt_id,
        kind=PoDiscrepancyKind.over,
        qty_ordered=line.qty_ordered,
        qty_received=line.qty_received,
        qty_difference=excess_added,
        created_by=user_id,
    )


def _load_history_sources(session: Session, po_id: int) -> PoHistorySources:
    line_rows = session.execute(
        select(PurchaseOrderLine.id, Product.code, Product.name, PurchaseOrderLine.qty_ordered)
        .join(Product, Product.id == PurchaseOrderLine.product_id)
        .where(PurchaseOrderLine.po_id == po_id)
        .order_by(PurchaseOrderLine.id)
    ).all()
    products_by_line = {
        line_id: PoLineProduct(code=code, name=name, qty_ordered=qty_ordered)
        for line_id, code, name, qty_ordered in line_rows
    }
    discrepancies = session.execute(
        select(PurchaseOrderDiscrepancy)
        .where(PurchaseOrderDiscrepancy.po_id == po_id)
        .order_by(PurchaseOrderDiscrepancy.id)
    ).scalars()

    shortfalls: list[PurchaseOrderDiscrepancy] = []
    over_receipts_by_receipt: dict[int, list[PurchaseOrderDiscrepancy]] = defaultdict(list)
    for discrepancy in discrepancies:
        if discrepancy.kind == PoDiscrepancyKind.short:
            shortfalls.append(discrepancy)
        elif discrepancy.receipt_id is not None:
            over_receipts_by_receipt[discrepancy.receipt_id].append(discrepancy)
    return PoHistorySources(
        products_by_line=products_by_line,
        shortfalls=shortfalls,
        over_receipts_by_receipt=over_receipts_by_receipt,
    )


def _history_comment(audit: AuditLog) -> str | None:
    if audit.action != "receive":
        return None
    # Receipts audited before migration 0021 carry no comment key.
    return audit.after_data.get("comment")


def _history_lines(
    history_action: PoHistoryAction,
    audit: AuditLog,
    sources: PoHistorySources,
) -> list[PoHistoryLine]:
    if history_action == "created":
        return _ordered_history_lines(sources)
    if history_action == "edited":
        return _edited_history_lines(audit)
    if history_action == "received":
        return _received_history_lines(audit, sources)
    if history_action == "closed_short":
        return _shortfall_history_lines(sources)
    return _reversed_history_lines(audit, sources)


def _ordered_history_lines(sources: PoHistorySources) -> list[PoHistoryLine]:
    return [
        PoHistoryLine(label=product.name, detail=f"ordered {product.qty_ordered}")
        for product in sources.products_by_line.values()
    ]


def _edited_history_lines(audit: AuditLog) -> list[PoHistoryLine]:
    edited_lines: list[PoHistoryLine] = []
    for field_name, new_value in audit.after_data.items():
        old_value = audit.before_data.get(field_name)
        edited_lines.append(
            PoHistoryLine(
                label=EDITABLE_FIELD_LABELS.get(field_name, field_name),
                detail=f"{old_value or '-'} -> {new_value or '-'}",
            )
        )
    return edited_lines


def _received_history_lines(audit: AuditLog, sources: PoHistorySources) -> list[PoHistoryLine]:
    receipt_id = audit.after_data.get("receipt_id")
    over_receipts = sources.over_receipts_by_receipt.get(receipt_id, [])
    excess_by_line = {over.po_line_id: over.qty_difference for over in over_receipts}

    received_lines: list[PoHistoryLine] = []
    for received in audit.after_data["received"]:
        po_line_id = received["po_line_id"]
        detail = f"received {received['qty_received']}"
        excess = excess_by_line.get(po_line_id)
        if excess is not None:
            detail += f" ({excess} more than ordered)"
        received_lines.append(
            PoHistoryLine(label=sources.products_by_line[po_line_id].name, detail=detail)
        )
    return received_lines


def _shortfall_history_lines(sources: PoHistorySources) -> list[PoHistoryLine]:
    shortfall_lines: list[PoHistoryLine] = []
    for shortfall in sources.shortfalls:
        detail = (
            f"ordered {shortfall.qty_ordered}, received {shortfall.qty_received}, "
            f"short {shortfall.qty_difference}"
        )
        if shortfall.reason is not None:
            detail += f" ({DISCREPANCY_REASON_LABELS[shortfall.reason]})"
        if shortfall.comment:
            detail += f": {shortfall.comment}"
        shortfall_lines.append(
            PoHistoryLine(
                label=sources.products_by_line[shortfall.po_line_id].name,
                detail=detail,
            )
        )
    return shortfall_lines


def _reversed_history_lines(audit: AuditLog, sources: PoHistorySources) -> list[PoHistoryLine]:
    # Cancels audited before the timeline existed did not record their reversed lines.
    reversed_lines = audit.after_data.get("reversed", [])
    return [
        PoHistoryLine(
            label=sources.products_by_line[reversed_line["po_line_id"]].name,
            detail=f"{reversed_line['qty']} units taken back out of warehouse stock",
        )
        for reversed_line in reversed_lines
    ]


def _menu_need_by_product(
    session: Session,
    *,
    year: int,
    week: int,
    day_names: list[str],
) -> dict[int, int]:
    need_rows = session.execute(
        select(MenuLine.product_id, func.sum(MenuLine.qty))
        .join(WeeklyMenu, WeeklyMenu.id == MenuLine.menu_id)
        .where(
            WeeklyMenu.year == year,
            WeeklyMenu.iso_week == week,
            WeeklyMenu.day_name.in_(day_names),
        )
        .group_by(MenuLine.product_id)
        .having(func.sum(MenuLine.qty) > 0)
    ).all()
    return {product_id: int(need_qty) for product_id, need_qty in need_rows}


def _plan_lines_by_supplier(
    session: Session,
    need_by_product: dict[int, int],
) -> dict[int | None, list[MenuOrderPlanLine]]:
    """Plan lines grouped by supplier id (None = product without a supplier), sorted by name."""
    product_ids = list(need_by_product)
    products = session.execute(select(Product).where(Product.id.in_(product_ids))).scalars()
    balance_rows = session.execute(
        text(
            "SELECT product_id, physical_qty, on_order_qty FROM v_stock_balances "
            "WHERE product_id IN :product_ids"
        ).bindparams(bindparam("product_ids", expanding=True)),
        {"product_ids": product_ids},
    ).all()
    balances_by_product = {row.product_id: row for row in balance_rows}

    lines_by_supplier: dict[int | None, list[MenuOrderPlanLine]] = defaultdict(list)
    for product in products:
        balance = balances_by_product[product.id]
        need_qty = need_by_product[product.id]
        lines_by_supplier[product.supplier_id].append(
            MenuOrderPlanLine(
                product_id=product.id,
                product_code=product.code,
                product_name=product.name,
                need_qty=need_qty,
                in_stock_qty=balance.physical_qty,
                on_order_qty=balance.on_order_qty,
                to_order_qty=compute_to_order_qty(
                    need_qty,
                    balance.physical_qty,
                    balance.on_order_qty,
                ),
                unit_price=product.purchase_price,
                vat_rate=product.vat_rate,
            )
        )
    for plan_lines in lines_by_supplier.values():
        plan_lines.sort(key=_plan_line_sort_key)
    return lines_by_supplier


def _supplier_names(session: Session, supplier_ids: list[int]) -> dict[int, str]:
    supplier_rows = session.execute(
        select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids))
    ).all()
    return {supplier_id: name for supplier_id, name in supplier_rows}


def _plan_line_sort_key(plan_line: MenuOrderPlanLine) -> str:
    return plan_line.product_name.lower()


def _supplier_sort_key(supplier: MenuOrderPlanSupplier) -> str:
    return supplier.supplier_name.lower()
