"""Sync bookkeeping tables — NOT present in schema.sql (introduced by spec 0004).

These two tables are created from ORM metadata via ``create_all(checkfirst=True)``
in ``scripts/apply_schema.py`` (schema.sql does not define them):

* ``sync_run``        — one row per Husky sync chunk (raw-first ELT audit trail,
                        resumable/auditable).
* ``stock_snapshots`` — point-in-time stock captures (GET /stock/current is
                        point-in-time only, so history must be snapshotted).
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncRun(Base):
    __tablename__ = "sync_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'empty', 'failed')",
            name="chk_sync_run_status_values",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    window_from: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    window_to: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'running'")
    )
    records_fetched: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    records_upserted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    blob_path: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class StockSnapshot(Base):
    __tablename__ = "stock_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "taken_at",
            "fridge_id",
            "product_code",
            name="uq_stock_snapshots_taken_fridge_code",
        ),
        CheckConstraint("units >= 0", name="chk_stock_snapshots_units_nonneg"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    taken_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id"), nullable=False
    )
    # NULLable: snapshots can arrive for products not yet mapped in the catalogue.
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("products.id"))
    product_code: Mapped[str] = mapped_column(Text, nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
