"""Operational models — purchase orders (SECTION 3), dispatch (SECTION 5), stock
ledger (SECTION 6), reconciliation (SECTION 8), and finance/alerts/audit
(SECTION 9). Mirrors: order_no_counters, purchase_orders, purchase_order_lines,
dispatches, dispatch_lines, stock_movements, restock_verifications,
restock_verification_lines, weekly_financials, alerts, audit_log.

NOTE: ``weekly_financials`` (schema.sql SECTION 9) was not named in the model-
split brief; it is a finance table and is mirrored here alongside alerts/audit.

NOTE: schema.sql attaches PL/pgSQL triggers to ``stock_movements``
(non-negativity enforcement + append-only guard) and a ``next_order_no()``
function / ``v_stock_balances`` view. Those are behavioural DB objects created by
schema.sql — the ORM models below intentionally do not reproduce them.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    ALERT_TYPE_ENUM,
    DISPATCH_STATUS_ENUM,
    LINE_SOURCE_ENUM,
    PO_STATUS_ENUM,
    STOCK_MOVEMENT_TYPE_ENUM,
    AlertType,
    DispatchStatus,
    LineSource,
    PoStatus,
    StockMovementType,
    enum_check,
)


class OrderNoCounter(Base):
    """Per-year counter behind next_order_no() (R4)."""

    __tablename__ = "order_no_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_seq: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            r"order_no ~ '^\d{4}-\d{5}$'", name="chk_purchase_orders_order_no_format"
        ),
        CheckConstraint(
            "expected_delivery_date >= order_date",
            name="chk_purchase_orders_delivery_after_order",
        ),
        enum_check("status", PoStatus, "chk_purchase_orders_status"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    order_no: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id"), nullable=False
    )
    status: Mapped[PoStatus] = mapped_column(
        PO_STATUS_ENUM, nullable=False, server_default=text("'pending'")
    )
    order_date: Mapped[datetime.date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    expected_delivery_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    # R5: totals accumulate ex-VAT, VAT and incl-VAT separately (cents, BIGINT).
    total_ex_vat: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    total_vat: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    total_incl_vat: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("po_id", "product_id", name="uq_purchase_order_lines_po_product"),
        CheckConstraint("qty_ordered > 0", name="chk_purchase_order_lines_qty_ordered_positive"),
        CheckConstraint(
            "qty_received >= 0", name="chk_purchase_order_lines_qty_received_nonneg"
        ),
        CheckConstraint("unit_price >= 0", name="chk_purchase_order_lines_unit_price_nonneg"),
        CheckConstraint(
            "vat_rate >= 0 AND vat_rate < 1",
            name="chk_purchase_order_lines_vat_rate_fraction",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    po_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    qty_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_received: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    unit_price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # cents
    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default=text("0")
    )


class Dispatch(Base):
    __tablename__ = "dispatches"
    __table_args__ = (
        # R7: exactly one dispatch batch per delivery date.
        Index("uq_dispatches_delivery_date", "delivery_date", unique=True),
        CheckConstraint("iso_week BETWEEN 1 AND 53", name="chk_dispatches_iso_week_range"),
        CheckConstraint("weekday BETWEEN 1 AND 7", name="chk_dispatches_weekday_iso"),
        CheckConstraint(
            "status NOT IN ('dispatched', 'reconciled') OR confirmed_at IS NOT NULL",
            name="chk_dispatches_confirmed_stamp",
        ),
        enum_check("status", DispatchStatus, "chk_dispatches_status"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    delivery_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # ISO: 1=Mon
    status: Mapped[DispatchStatus] = mapped_column(
        DISPATCH_STATUS_ENUM, nullable=False, server_default=text("'draft'")
    )
    confirmed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    confirmed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DispatchLine(Base):
    """RANGE-partitioned monthly on ``delivery_date`` (migration 0004).

    ``delivery_date`` is denormalised from the parent ``dispatches`` row so it
    can serve as the partition key (mirrors the ``sales_events`` pattern). The
    partition key must be part of every unique key, so the PK is composite
    ``(id, delivery_date)`` and the natural key gains ``delivery_date``. Callers
    MUST set ``delivery_date = dispatch.delivery_date`` on insert; a dispatch's
    delivery date is immutable, so the denormalised value never drifts.
    """

    __tablename__ = "dispatch_lines"
    __table_args__ = (
        PrimaryKeyConstraint("id", "delivery_date", name="dispatch_lines_pkey"),
        UniqueConstraint(
            "dispatch_id",
            "fridge_id",
            "product_id",
            "delivery_date",
            name="uq_dispatch_lines_dispatch_fridge_product",
        ),
        CheckConstraint("qty > 0", name="chk_dispatch_lines_qty_positive"),
        enum_check("source", LineSource, "chk_dispatch_lines_source"),
        # vat_rate is a fraction in [0, 1) when present (mirrors products.vat_rate
        # and purchase_order_lines.vat_rate); NULL means "no snapshot yet".
        CheckConstraint(
            "vat_rate IS NULL OR (vat_rate >= 0 AND vat_rate < 1)",
            name="chk_dispatch_lines_vat_rate",
        ),
        Index("ix_dispatch_lines_fridge", "fridge_id"),
        Index("ix_dispatch_lines_product", "product_id"),
        {"postgresql_partition_by": "RANGE (delivery_date)"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True))
    dispatch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dispatches.id", ondelete="CASCADE"), nullable=False
    )
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    # Denormalised partition key — callers MUST set it to the parent dispatch's
    # delivery_date (a partitioned table rejects a NULL partition key before any
    # trigger could fill it, so it cannot be server-defaulted).
    delivery_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[LineSource] = mapped_column(
        LINE_SOURCE_ENUM, nullable=False, server_default=text("'manual'")
    )
    # Price snapshots taken at confirm time (cents, BIGINT).
    unit_purchase_price: Mapped[int | None] = mapped_column(BigInteger)
    unit_sales_price: Mapped[int | None] = mapped_column(BigInteger)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))


class StockMovement(Base):
    """Append-only signed stock ledger (slide 24, R6). Non-negativity and
    immutability are enforced by triggers defined in schema.sql."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("qty <> 0", name="chk_stock_movements_qty_nonzero"),
        CheckConstraint(
            "(movement_type = 'po_receipt'            AND qty > 0) OR "
            "(movement_type = 'dispatch'              AND qty < 0) OR "
            "(movement_type = 'cancellation_reversal' AND qty < 0) OR "
            "(movement_type = 'adjustment')",
            name="chk_movement_sign",
        ),
        CheckConstraint(
            "movement_type <> 'adjustment' "
            "OR (reason IS NOT NULL AND btrim(reason) <> '')",
            name="chk_adjustment_reason",
        ),
        CheckConstraint(
            "(movement_type IN ('po_receipt', 'cancellation_reversal') AND po_line_id IS NOT NULL) OR "
            "(movement_type = 'dispatch'                               AND dispatch_line_id IS NOT NULL) OR "
            "(movement_type = 'adjustment')",
            name="chk_movement_reference",
        ),
        enum_check("movement_type", StockMovementType, "chk_stock_movements_movement_type"),
        Index("ix_stock_movements_product_created", "product_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    # Signed quantity; sign convention enforced per movement type.
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    movement_type: Mapped[StockMovementType] = mapped_column(
        STOCK_MOVEMENT_TYPE_ENUM, nullable=False
    )
    po_line_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("purchase_order_lines.id")
    )
    # No FK: dispatch_lines is RANGE-partitioned (composite PK id+delivery_date),
    # so a FK on id alone is impossible (migration 0004). Referential integrity
    # is enforced by the application; the id value is still stored for joins.
    dispatch_line_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RestockVerification(Base):
    """One reconciliation run per dispatch (R9)."""

    __tablename__ = "restock_verifications"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    dispatch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dispatches.id", ondelete="CASCADE"), nullable=False
    )
    run_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))


class RestockVerificationLine(Base):
    __tablename__ = "restock_verification_lines"
    __table_args__ = (
        UniqueConstraint(
            "verification_id",
            "fridge_id",
            "product_id",
            name="uq_restock_verification_lines_run_fridge_product",
        ),
        CheckConstraint(
            "dispatched_qty >= 0", name="chk_restock_verification_lines_dispatched_nonneg"
        ),
        CheckConstraint(
            "added_qty >= 0", name="chk_restock_verification_lines_added_nonneg"
        ),
        CheckConstraint(
            "unreliable_qty >= 0", name="chk_restock_verification_lines_unreliable_nonneg"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    verification_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("restock_verifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    dispatched_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    added_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # UNRELIABLE tags: counted separately, excluded from diff totals (R9).
    unreliable_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    diff_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # Valued at buy price (R9). Cents, BIGINT.
    diff_value: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )


class WeeklyFinancial(Base):
    """Weekly manual finance inputs + fee snapshots (R10)."""

    __tablename__ = "weekly_financials"
    __table_args__ = (
        UniqueConstraint("year", "iso_week", name="uq_weekly_financials_year_week"),
        CheckConstraint("year BETWEEN 2020 AND 2100", name="chk_weekly_financials_year_range"),
        CheckConstraint(
            "iso_week BETWEEN 1 AND 53", name="chk_weekly_financials_iso_week_range"
        ),
        CheckConstraint(
            "drops_count >= 0", name="chk_weekly_financials_drops_count_nonneg"
        ),
        CheckConstraint(
            "unsold_items >= 0", name="chk_weekly_financials_unsold_items_nonneg"
        ),
        CheckConstraint(
            "fridge_count IS NULL OR fridge_count >= 0",
            name="chk_weekly_financials_fridge_count_nonneg",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    # Manual weekly money inputs (R10) — cents, BIGINT.
    catering_turnover: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    catering_food_cost: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    tgtg_turnover: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    logistics_cost: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    drops_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    unsold_items: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # Manual per-week fridge count (Weekly View input). NULL = not entered.
    fridge_count: Mapped[int | None] = mapped_column(Integer)
    remarks: Mapped[str | None] = mapped_column(Text)
    # Fee snapshots: rates in force when the week was closed.
    # pos_fee_pct_snapshot is a fraction (NOT money) — stays NUMERIC.
    pos_fee_pct_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default=text("0.09")
    )
    # rfid_fee_snapshot is money in cents (EUR 0.10 -> 10) — BIGINT.
    rfid_fee_snapshot: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("10")
    )
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Alert(Base):
    """Replaces Power Automate alert emails (slide 12)."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="chk_alerts_status_values",
        ),
        enum_check("alert_type", AlertType, "chk_alerts_alert_type"),
        Index("ix_alerts_open", "created_at", postgresql_where=text("status = 'open'")),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    alert_type: Mapped[AlertType] = mapped_column(ALERT_TYPE_ENUM, nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'open'")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    acknowledged_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id")
    )
    acknowledged_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class AuditLog(Base):
    """User + timestamp + before/after for every mutating action (slide 23)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity", "entity_id", "at"),)

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    before_data: Mapped[dict | None] = mapped_column(JSONB)
    after_data: Mapped[dict | None] = mapped_column(JSONB)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
