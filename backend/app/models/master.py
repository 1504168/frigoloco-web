"""Master data models - SECTION 2 of schema.sql plus the ``settings`` table
(SECTION 9). Mirrors: users, suppliers, categories, products, clients, fridges,
fridge_product_prices, fridge_delivery_config, client_fees,
client_service_charges, client_contacts, client_interventions, product_targets,
menu_product_caps, settings, supplier_agreements, supplier_delivery_schedules,
product_tags, client_rules, equipment.
"""

from __future__ import annotations

import datetime
import enum
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
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    CLIENT_CONTACT_ROLE_ENUM,
    USER_ROLE_ENUM,
    ClientContactRole,
    UserRole,
    enum_check,
)


class SupplierAgreementBasis(str, enum.Enum):
    year_end_rebate = "year_end_rebate"
    price_discount = "price_discount"


class ClientRuleType(str, enum.Enum):
    exclude_tag = "exclude_tag"
    note = "note"


class EquipmentCategory(str, enum.Enum):
    coffee = "coffee"
    water_filter = "water_filter"
    vending = "vending"
    fridge = "fridge"
    other = "other"


class EquipmentOwnership(str, enum.Enum):
    bought = "bought"
    rent = "rent"


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
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint(
            "payment_terms_days >= 0", name="chk_suppliers_payment_terms_days_nonneg"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    warehouse_address: Mapped[str | None] = mapped_column(Text)
    # Person to call when goods do not arrive. Local-only.
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    # Days after the invoice (30, 60); end_of_month = counted from the end of the invoice month.
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    payment_terms_end_of_month: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Not unique: two "2." categories share a prefix; lists break ties by name.
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
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
            "price_ex_surcharges >= 0",
            name="chk_products_price_ex_surcharges_nonneg",
        ),
        CheckConstraint(
            "local_status IN ('inactive', 'cancelled')",
            name="chk_products_local_status_values",
        ),
        CheckConstraint("min_stock_qty >= 0", name="chk_products_min_stock_qty_nonneg"),
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
    # Money in minor units (cents), BIGINT - see schema.sql header convention.
    purchase_price: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    sales_price: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    # VAT as a fraction (R5): 0.06 = 6 %. NOT money - stays NUMERIC.
    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default=text("0")
    )
    # NULLable: 218 products arrive from Husky without expiry days (backfill task).
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    # Husky /producttype extras retained for future use (store-only, NULLable):
    # free-text description, currency, and the sales price BEFORE POS/RFID
    # surcharges (RAW cents, like sales_price).
    description: Mapped[str | None] = mapped_column(Text)
    currency_code: Mapped[str | None] = mapped_column(Text)
    price_ex_surcharges: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Manual status override (D5): NULL follows Husky, else user-forced and wins
    # over sync. LOCAL-owned - the Husky sync contract never writes this column.
    local_status: Mapped[str | None] = mapped_column(Text)
    # Warehouse minimum: below it a low_stock alert opens. NULL = no minimum. Local-only.
    min_stock_qty: Mapped[int | None] = mapped_column(Integer)
    # Position on the printed dispatch sheet inside its category. Local-only.
    print_order: Mapped[int | None] = mapped_column(Integer)
    husky_synced_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def effective_status(self) -> str:
        """Effective status: local override wins, else Husky-derived is_active."""
        if self.local_status is not None:
            return self.local_status
        return "active" if self.is_active else "inactive"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    preferences: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
    # over sync. LOCAL-owned - the Husky sync contract never writes this column.
    local_status: Mapped[str | None] = mapped_column(Text)
    modem_number: Mapped[str | None] = mapped_column(Text)
    sim_card_number: Mapped[str | None] = mapped_column(Text)
    # False = closed Saturday and Sunday: the forecast skips weekend days.
    active_on_weekends: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Raw Husky status (LIVE, SHIPPED, END_OF_LIFE, ...); only LIVE makes is_active true.
    husky_status: Mapped[str | None] = mapped_column(Text)
    # Free-text site preferences (what they like or refuse). Local-only.
    preferences: Mapped[str | None] = mapped_column(Text)
    # Delivery window; from > to is valid and means a window across midnight. Local-only.
    delivery_time_from: Mapped[datetime.time | None] = mapped_column(Time)
    delivery_time_to: Mapped[datetime.time | None] = mapped_column(Time)
    night_delivery_ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
        CheckConstraint(
            "price_ex_surcharges >= 0",
            name="chk_fridge_product_prices_ex_surcharges_nonneg",
        ),
        CheckConstraint(
            "vat_rate >= 0 AND vat_rate < 1",
            name="chk_fridge_product_prices_vat_fraction",
        ),
    )

    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    sales_price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # cents
    # Husky /fridgeproductprice extras (store-only, NULLable): price before
    # surcharges (RAW cents), per-fridge VAT fraction, and currency.
    price_ex_surcharges: Mapped[int | None] = mapped_column(BigInteger)  # cents
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    currency_code: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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


class ClientContact(Base):
    """One contact person per (client, role)."""

    __tablename__ = "client_contacts"
    __table_args__ = (
        PrimaryKeyConstraint("client_id", "role"),
        enum_check("role", ClientContactRole, "chk_client_contacts_role"),
    )

    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ClientContactRole] = mapped_column(CLIENT_CONTACT_ROLE_ENUM, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    job_title: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FridgeIntervention(Base):
    """Maintenance or intervention on one fridge (table name kept from the first version)."""

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
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Setting(Base):
    """Tunable settings (SECTION 9): scoring weights, margins, fees, thresholds."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SupplierAgreement(Base):
    """Yearly negotiated discount with a supplier. Reference data: no price or P&L effect."""

    __tablename__ = "supplier_agreements"
    __table_args__ = (
        enum_check("basis", SupplierAgreementBasis, "chk_supplier_agreements_basis"),
        CheckConstraint(
            "discount_pct >= 0 AND discount_pct <= 100",
            name="chk_supplier_agreements_discount_pct_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    # A percentage, 2.5 = 2.5 %. Not money.
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    review_date: Mapped[datetime.date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SupplierDeliverySchedule(Base):
    """One delivery weekday of a supplier and the order cutoff that delivery needs."""

    __tablename__ = "supplier_delivery_schedules"
    __table_args__ = (
        PrimaryKeyConstraint("supplier_id", "delivery_weekday"),
        CheckConstraint(
            "delivery_weekday BETWEEN 1 AND 7",
            name="chk_supplier_delivery_schedules_delivery_weekday_iso",
        ),
        CheckConstraint(
            "cutoff_weekday BETWEEN 1 AND 7",
            name="chk_supplier_delivery_schedules_cutoff_weekday_iso",
        ),
    )

    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    delivery_weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # ISO: 1=Mon
    # Same weekday as the delivery = order the same day before the cutoff time.
    cutoff_weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    cutoff_time: Mapped[datetime.time] = mapped_column(Time, nullable=False)


class ProductTag(Base):
    """A dietary or content tag on a product (contains_pork, vegan, ...). Local-only."""

    __tablename__ = "product_tags"
    __table_args__ = (
        PrimaryKeyConstraint("product_id", "tag"),
        CheckConstraint("tag ~ '^[a-z0-9_]+$'", name="chk_product_tags_tag_format"),
    )

    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(Text, nullable=False)


class ClientRule(Base):
    """A client rule: exclude products with a tag, or a free note. fridge_id NULL = all fridges."""

    __tablename__ = "client_rules"
    __table_args__ = (
        enum_check("rule_type", ClientRuleType, "chk_client_rules_rule_type"),
        CheckConstraint(
            "rule_type <> 'exclude_tag' OR tag IS NOT NULL",
            name="chk_client_rules_exclude_tag_has_tag",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="chk_client_rules_valid_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    fridge_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fridges.id", ondelete="CASCADE")
    )
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    tag: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime.date | None] = mapped_column(Date)
    valid_to: Mapped[datetime.date | None] = mapped_column(Date)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Equipment(Base):
    """Equipment register (coffee machines, water filters, ...). Reference data: no P&L effect."""

    __tablename__ = "equipment"
    __table_args__ = (
        enum_check("equipment_category", EquipmentCategory, "chk_equipment_category"),
        enum_check("ownership", EquipmentOwnership, "chk_equipment_ownership"),
        CheckConstraint(
            "purchase_price_cents >= 0", name="chk_equipment_purchase_price_nonneg"
        ),
        CheckConstraint(
            "monthly_rent_cost_cents >= 0", name="chk_equipment_monthly_rent_cost_nonneg"
        ),
        CheckConstraint("monthly_fee_cents >= 0", name="chk_equipment_monthly_fee_nonneg"),
        CheckConstraint("financing_years > 0", name="chk_equipment_financing_years_positive"),
        CheckConstraint(
            "financing_rate >= 0 AND financing_rate < 1",
            name="chk_equipment_financing_rate_fraction",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    machine_type: Mapped[str] = mapped_column(Text, nullable=False)
    equipment_category: Mapped[str] = mapped_column(Text, nullable=False)
    machine_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("suppliers.id"))
    client_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("clients.id"))
    fridge_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("fridges.id"))
    ownership: Mapped[str] = mapped_column(Text, nullable=False)
    purchase_price_cents: Mapped[int | None] = mapped_column(BigInteger)
    # What we pay the supplier each month for a rented machine.
    monthly_rent_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    # What we charge the client each month for this machine.
    monthly_fee_cents: Mapped[int | None] = mapped_column(BigInteger)
    purchase_date: Mapped[datetime.date | None] = mapped_column(Date)
    financing_years: Mapped[int | None] = mapped_column(Integer)
    # A fraction, 0.04 = 4 %. Not money.
    financing_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    financed_by: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
