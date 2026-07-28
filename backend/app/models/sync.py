"""Sync bookkeeping tables (introduced by spec 0004).

* ``sync_run``     - one row per Husky sync chunk (raw-first ELT audit trail,
                     resumable/auditable). NOT present in schema.sql: created
                     from ORM metadata via ``create_all(checkfirst=True)`` in
                     ``scripts/apply_schema.py``.
* ``fridge_stock`` - latest-known in-fridge stock from ``GET /stock/current``:
                     ONE row per (fridge, product), overwritten in place by the
                     snapshot job. It is a cache of current state, not a time
                     series - no stock history is kept, because nothing reads it
                     (the only consumer is the menu allocation engine, which
                     needs the current value). Mark-and-sweep: each run stamps a
                     single shared ``taken_at`` and deletes older rows, so the
                     table mirrors the last vendor response exactly and a missing
                     row means "not in that fridge right now". Defined in
                     schema.sql AND here (migration 0009).

Warehouse stock is a different thing entirely - see ``v_stock_balances``.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
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


class FridgeStock(Base):
    __tablename__ = "fridge_stock"
    __table_args__ = (
        CheckConstraint("units >= 0", name="chk_fridge_stock_units_nonneg"),
        Index("ix_fridge_stock_product", "product_id"),
    )

    # (fridge_id, product_code) is the identity, NOT product_id: product_id is
    # NULLable (unmapped vendor codes) and so cannot key the row.
    fridge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fridges.id"), primary_key=True
    )
    product_code: Mapped[str] = mapped_column(Text, primary_key=True)
    # NULLable: snapshots can arrive for products not yet in the catalogue.
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("products.id"))
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    # One shared generation timestamp per snapshot run (mark-and-sweep).
    taken_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
