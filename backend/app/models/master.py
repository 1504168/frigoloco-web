"""Master data models — SECTION 2 of schema.sql plus the ``settings`` table
(SECTION 9). Mirrors: users, suppliers, categories, products, clients, fridges,
fridge_product_prices, fridge_delivery_config, client_fees,
client_service_charges, client_interventions, product_targets,
menu_product_caps, settings.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
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
from app.models.enums import USER_ROLE_ENUM, UserRole, enum_check


class User(Base):
    __tablename__ = "users"
    __table_args__ = (enum_check("role", UserRole, "chk_users_role"),)

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(USER_ROLE_ENUM, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    warehouse_address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    # Fixed order in which categories print on driver delivery sheets (R8).
    dispatch_print_order: Mapped[int] = mapped_column(
        Integer, nullable=False, unique=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("purchase_price >= 0", name="chk_products_purchase_price_nonneg"),
        CheckConstraint("sales_price >= 0", name="chk_products_sales_price_nonneg"),
        CheckConstraint(
            "vat_rate >= 0 AND vat_rate < 1", name="chk_products_vat_rate_fraction"
        ),
        CheckConstraint("shelf_life_days > 0", name="chk_products_shelf_life_positive"),
        CheckConstraint(
            "local_status IN ('inactive', 'cancelled')",
            name="chk_products_local_status_values",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    # TEXT on purpose: barcodes/product codes keep leading zeros.
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False
    )
    supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("suppliers.id")
    )
    # Money in minor units (cents), BIGINT — see schema.sql header convention.
    purchase_price: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    sales_price: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    # VAT as a fraction (R5): 0.06 = 6 %. NOT money — stays NUMERIC.
    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default=text("0")
    )
    # NULLable: 218 products arrive from Husky without expiry days (backfill task).
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Manual status override (D5): NULL follows Husky, else user-forced and wins
    # over sync. LOCAL-owned — the Husky sync contract never writes this column.
    local_status: Mapped[str | None] = mapped_column(Text)
    husky_synced_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def effective_status(self) -> str:
        """Effective status: local override wins, else Husky-derived is_active."""
        if self.local_status is not None:
            return self.local_status
        return "active" if self.is_active else "inactive"


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint("workers_count >= 0", name="chk_clients_workers_count_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    workers_count: Mapped[int | None] = mapped_column(Integer)
    worker_type: Mapped[str | None] = mapped_column(Text)
    preferences: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Fridge(Base):
    __tablename__ = "fridges"
    __table_args__ = (
        CheckConstraint(
            "local_status IN ('inactive', 'cancelled')",
            name="chk_fridges_local_status_values",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    # Husky device id, e.g. 'if-0001120'.
    husky_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    husky_name: Mapped[str | None] = mapped_column(Text)
    friendly_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    client_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("clients.id"))
    delivery_address: Mapped[str | None] = mapped_column(Text)
    delivery_instructions: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Manual status override (D5): NULL follows Husky, else user-forced and wins
    # over sync. LOCAL-owned — the Husky sync contract never writes this column.
    local_status: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def effective_status(self) -> str:
        """Effective status: local override wins, else Husky-derived is_active."""
        if self.local_status is not None:
            return self.local_status
        return "active" if self.is_active else "inactive"


class FridgeProductPrice(Base):
    """Per-fridge sales-price overrides (briefing slide 24)."""

    __tablename__ = "fridge_product_prices"
    __table_args__ = (
        PrimaryKeyConstraint("fridge_id", "product_id"),
        CheckConstraint("sales_price >= 0", name="chk_fridge_product_prices_price_nonneg"),
    )

    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    sales_price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # cents
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FridgeDeliveryConfig(Base):
    """Forecast V2 columns C-E: per delivery weekday inputs (R1)."""

    __tablename__ = "fridge_delivery_config"
    __table_args__ = (
        PrimaryKeyConstraint("fridge_id", "weekday"),
        CheckConstraint(
            "weekday BETWEEN 1 AND 7", name="chk_fridge_delivery_config_weekday_iso"
        ),
        CheckConstraint(
            "min_daily_qty >= 0", name="chk_fridge_delivery_config_min_daily_nonneg"
        ),
        CheckConstraint(
            "days_to_fill > 0", name="chk_fridge_delivery_config_days_to_fill_positive"
        ),
    )

    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # ISO: 1=Mon
    min_daily_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    days_to_fill: Mapped[int] = mapped_column(Integer, nullable=False)


class ClientFee(Base):
    __tablename__ = "client_fees"
    __table_args__ = (
        CheckConstraint("yearly_fee >= 0", name="chk_client_fees_yearly_fee_nonneg"),
        CheckConstraint(
            "contract_end IS NULL OR contract_end >= contract_start",
            name="chk_client_fees_contract_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    yearly_fee: Mapped[int] = mapped_column(BigInteger, nullable=False)  # cents
    contract_start: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    contract_end: Mapped[datetime.date | None] = mapped_column(Date)


class ClientServiceCharge(Base):
    __tablename__ = "client_service_charges"
    __table_args__ = (
        CheckConstraint(
            "month = date_trunc('month', month)::date",
            name="chk_client_service_charges_month_first_day",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    # First day of the month the one-off charge belongs to.
    month: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # cents
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClientIntervention(Base):
    __tablename__ = "client_interventions"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id", ondelete="CASCADE"), nullable=False
    )
    intervention_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductTarget(Base):
    """Snacks & Drinks target-based replenishment (R3)."""

    __tablename__ = "product_targets"
    __table_args__ = (
        PrimaryKeyConstraint("fridge_id", "product_id"),
        CheckConstraint("target_qty >= 0", name="chk_product_targets_target_nonneg"),
    )

    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    target_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MenuProductCap(Base):
    """Max units of a product one fridge may receive per dispatch (slide 8)."""

    __tablename__ = "menu_product_caps"
    __table_args__ = (
        PrimaryKeyConstraint("fridge_id", "product_id"),
        CheckConstraint("max_qty > 0", name="chk_menu_product_caps_max_qty_positive"),
    )

    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    max_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Setting(Base):
    """Tunable settings (SECTION 9): scoring weights, margins, fees, thresholds."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
