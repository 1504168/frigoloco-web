"""Menus, forecasts, scores - SECTION 4 of schema.sql. Mirrors: weekly_menus,
menu_products, forecast_runs, forecast_results, product_scores,
fridge_product_scores.
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
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import MENU_STATUS_ENUM, MenuStatus, enum_check


class WeeklyMenu(Base):
    __tablename__ = "weekly_menus"
    __table_args__ = (
        # (year, iso_week, day_name) natural key (migration 0005). day_name '' is
        # the legacy week-level menu; a workflow menu carries the ISO weekday.
        UniqueConstraint(
            "year", "iso_week", "day_name", name="uq_weekly_menus_year_week_day"
        ),
        CheckConstraint(
            "year BETWEEN 2020 AND 2100", name="chk_weekly_menus_year_range"
        ),
        CheckConstraint(
            "iso_week BETWEEN 1 AND 53", name="chk_weekly_menus_iso_week_range"
        ),
        enum_check("status", MenuStatus, "chk_weekly_menus_status"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    # ISO weekday name (Monday..Sunday); '' = legacy week-level menu (migration 0005).
    day_name: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    status: Mapped[MenuStatus] = mapped_column(
        MENU_STATUS_ENUM, nullable=False, server_default=text("'draft'")
    )
    copied_from_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("weekly_menus.id")
    )
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MenuProduct(Base):
    __tablename__ = "menu_products"
    __table_args__ = (PrimaryKeyConstraint("menu_id", "product_id"),)

    menu_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("weekly_menus.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )


class MenuLine(Base):
    """Per-fridge x product quantity grid a SAVED workflow menu carries (D2).

    ``menu_products`` records membership only; ``menu_lines`` (migration 0005)
    adds the fridge-level quantities the D2 grid needs. ``category_id`` is
    denormalised for the category-banded grid render (== ``products.category_id``).
    """

    __tablename__ = "menu_lines"
    __table_args__ = (
        UniqueConstraint(
            "menu_id",
            "fridge_id",
            "product_id",
            name="uq_menu_lines_menu_fridge_product",
        ),
        CheckConstraint("qty >= 0", name="chk_menu_lines_qty_nonneg"),
        Index("ix_menu_lines_menu", "menu_id"),
        Index("ix_menu_lines_product", "product_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    menu_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("weekly_menus.id", ondelete="CASCADE"), nullable=False
    )
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (
        CheckConstraint(
            "model IN ('moving_average_3w')", name="chk_forecast_runs_model"
        ),
        # Exactly one SAVED forecast per delivery_date (== per iso year/week/day);
        # ephemeral compute rows (is_saved=false) are unconstrained (migration 0005).
        Index(
            "uq_forecast_runs_saved_delivery_date",
            "delivery_date",
            unique=True,
            postgresql_where=text("is_saved"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    run_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    delivery_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    # Extensible enum-style model selector (only 'moving_average_3w' today; migration 0005).
    model: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'moving_average_3w'")
    )
    # false = ephemeral /forecasts/run compute; true = the ONE persisted forecast
    # per (year, week, day) (migration 0005).
    is_saved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # ISO weekday name of delivery_date for saved runs; NULL for legacy compute rows.
    day_name: Mapped[str | None] = mapped_column(Text)
    # Snapshot of the parameters the run used (R1) - reproducible runs.
    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))


class ForecastResult(Base):
    __tablename__ = "forecast_results"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "fridge_id", "category_id", name="uq_forecast_results_run_fridge_cat"
        ),
        CheckConstraint("forecast_qty >= 0", name="chk_forecast_results_qty_nonneg"),
        CheckConstraint("valid_days >= 0", name="chk_forecast_results_valid_days_nonneg"),
        CheckConstraint(
            "holiday_days >= 0", name="chk_forecast_results_holiday_days_nonneg"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False
    )
    forecast_qty: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    valid_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    holiday_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )


class ProductScore(Base):
    """Yearly product scorecard (R2), recomputed nightly."""

    __tablename__ = "product_scores"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "period_end", name="uq_product_scores_product_period"
        ),
        CheckConstraint("sample_size >= 0", name="chk_product_scores_sample_size_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    period_end: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    pct_sold: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    review_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    margin_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    final_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    sample_size: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    computed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FridgeProductScore(Base):
    """Per-fridge product scores for the dual 50/50 scoring model (R2 target)."""

    __tablename__ = "fridge_product_scores"
    __table_args__ = (
        UniqueConstraint(
            "fridge_id",
            "product_id",
            "period_end",
            name="uq_fridge_product_scores_fridge_product_period",
        ),
        CheckConstraint(
            "sample_size >= 0", name="chk_fridge_product_scores_sample_size_nonneg"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    period_end: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    pct_sold: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    review_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    margin_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    final_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    sample_size: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    computed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
