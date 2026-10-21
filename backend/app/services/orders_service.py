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
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.money import to_cents
from app.models.master import Product, Supplier
from app.models.operations import (
    AuditLog,
    Dispatch,
    DispatchLine,
    PurchaseOrder,
    PurchaseOrderLine,
    StockMovement,
)
from app.models.enums import PoStatus, StockMovementType
from app.schemas.orders import (
    PoLineCreate,
    PurchaseOrderCreate,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
    StockMovementRead,
)


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
    session: Session, payload: PurchaseOrderCreate
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
    )
    session.commit()
    session.refresh(po)
    return _po_to_read(session, po)


def update_purchase_order(
    session: Session, po_id: int, payload: PurchaseOrderUpdate
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
    )
    session.commit()
    session.refresh(po)
    return _po_to_read(session, po)


def receive_purchase_order(
    session: Session,
    po_id: int,
    receipts: list[ReceiptLine],
    acknowledge_over_receipt: bool,
    user_id: int | None,
) -> tuple[PurchaseOrderRead, list[StockMovementRead]]:
    po = _get_po_or_404(session, po_id)
    if po.status != PoStatus.pending:
        raise ApiError(
            409, "conflict", f"purchase order is {po.status.value}, not pending"
        )

    lines = {
        line.id: line
        for line in session.execute(
            select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)
        ).scalars()
    }

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

    movements: list[StockMovement] = []
    for receipt in receipts:
        line = lines[receipt.po_line_id]
        line.qty_received += receipt.qty_received
        movement = StockMovement(
            product_id=line.product_id,
            qty=receipt.qty_received,
            movement_type=StockMovementType.po_receipt,
            po_line_id=line.id,
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
        after={"received": [r.__dict__ for r in receipts], "status": po.status.value},
    )
    session.commit()
    session.refresh(po)
    movement_reads = [StockMovementRead.model_validate(m) for m in movements]
    return _po_to_read(session, po), movement_reads


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
        after={"status": PoStatus.cancelled.value},
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
