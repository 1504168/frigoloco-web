"""Raw RFID event store — SECTION 7 of schema.sql. Mirrors: sales_events and
restock_events (both RANGE-partitioned by their timestamp), and product_reviews.

The partition parents and their monthly children, plus the
``create_event_partitions_for_month`` maintenance functions, are created by
schema.sql. ``postgresql_partition_by`` is declared here for fidelity, but these
ORM classes are never used to emit DDL (only the two sync tables are).
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    RESTOCK_ACTION_ENUM,
    TAG_STATUS_ENUM,
    RestockAction,
    TagStatus,
    enum_check,
)


class SalesEvent(Base):
    """One row per unit sold, from Husky GET /purchases (R10).
    Partitioned monthly on ``sold_at``."""

    __tablename__ = "sales_events"
    __table_args__ = (
        # Partition key must be part of the PK / unique keys.
        PrimaryKeyConstraint("id", "sold_at", name="sales_events_pkey"),
        UniqueConstraint("husky_ref", "sold_at", name="uq_sales_events_husky_ref"),
        Index("ix_sales_events_fridge_sold_at", "fridge_id", "sold_at"),
        Index("ix_sales_events_product_sold_at", "product_id", "sold_at"),
        {"postgresql_partition_by": "RANGE (sold_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    husky_ref: Mapped[str] = mapped_column(Text, nullable=False)
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    sold_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    unit_price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # cents
    is_refunded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    discount_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")  # cents
    )
    # Distinguishes FrigoLoco-provided discounts from customer credit (R10).
    discount_provider: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RestockEvent(Base):
    """One row per ADDED/REMOVED tag event, from Husky GET /restock (R9).
    Partitioned monthly on ``occurred_at``."""

    __tablename__ = "restock_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "occurred_at", name="restock_events_pkey"),
        UniqueConstraint(
            "husky_ref", "occurred_at", name="uq_restock_events_husky_ref"
        ),
        Index("ix_restock_events_fridge_occurred_at", "fridge_id", "occurred_at"),
        Index("ix_restock_events_product_occurred_at", "product_id", "occurred_at"),
        enum_check("action", RestockAction, "chk_restock_events_action"),
        enum_check("tag_status", TagStatus, "chk_restock_events_tag_status"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    husky_ref: Mapped[str] = mapped_column(Text, nullable=False)
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    action: Mapped[RestockAction] = mapped_column(RESTOCK_ACTION_ENUM, nullable=False)
    tag_status: Mapped[TagStatus] = mapped_column(
        TAG_STATUS_ENUM, nullable=False, server_default=text("'valid'")
    )
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    synced_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductReview(Base):
    """Customer ratings from Husky GET /productreview (R2). rating == 1 positive."""

    __tablename__ = "product_reviews"
    __table_args__ = (
        Index(
            "ix_product_reviews_product_reviewed_at", "product_id", "reviewed_at"
        ),
        # Husky ratings are a thumbs model: 1 = positive, -1/0 = negative
        # (scoring treats anything <> 1 as negative). Live data is {-1, 1}.
        CheckConstraint(
            "rating IN (-1, 0, 1)", name="chk_product_reviews_rating"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    husky_ref: Mapped[str | None] = mapped_column(Text, unique=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    fridge_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("fridges.id"))
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reviewed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    synced_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
