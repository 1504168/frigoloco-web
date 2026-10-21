"""Husky master-data & event sync - the importable domain layer (D5).

This module is the single home of the Husky sync/transform logic. It used to
live under ``cron/cron/jobs/*``; per work-order D5 it was relocated here so that
BOTH the APScheduler cron jobs AND the FastAPI ``/api/v1/sync`` router call the
exact same domain functions. ``cron.jobs.*`` are now thin wrappers importing
from here (no ``backend -> cron`` import - the dependency only flows one way).

It also owns the **field-ownership contract** (D5 requirement 1): for every
Husky-fed table there is an explicit list of the columns sync is allowed to
overwrite. Every upsert is routed through :func:`_guarded_update_set`, which
raises if a write would touch a column outside the Husky-owned / sync-managed
sets. ``local_status`` (the manual override) and every local-only column are in
neither set, so sync can never clobber them.

Effective-activity rule (D5 requirement 2): ``local_status`` wins. Sync only
ever writes ``is_active`` (derived from Husky presence). A row's *effective*
status is ``local_status`` when set, else ``active``/``inactive`` from
``is_active``. :func:`effective_status_clause` builds the matching SQL filter
the products/fridges list endpoints use for ``?status=``.
"""

from __future__ import annotations

import csv
import datetime
import gzip
import io
import json
import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from functools import partial
from pathlib import Path
from types import TracebackType

from pydantic import BaseModel
from sqlalchemy import Table, and_, column, delete, func, or_, select, table, text, update
from sqlalchemy.dialects.postgresql import Insert, insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.husky.archive import archive_raw
from app.husky.client import FetchResult, HuskyClient
from app.husky.normalize import (
    euros_to_minor_units,
    first_discount_provider,
    is_refunded,
    normalize_vat_fraction,
    sum_discount_minor_units,
)
from app.husky.schemas import (
    CurrentStock,
    FacilityItem,
    FridgeItem,
    ProductFridgeItem,
    ProductReviewItem,
    ProductTypeItem,
)
from app.models import (
    Category,
    Client,
    Fridge,
    FridgeProductPrice,
    FridgeStock,
    Product,
    ProductReview,
    RestockEvent,
    SalesEvent,
    Supplier,
    SyncRun,
)

logger = logging.getLogger("husky.sync")


# ===========================================================================
# Time helpers
# ===========================================================================


def utcnow() -> datetime.datetime:
    """Timezone-aware UTC now (all event timestamps are ``TIMESTAMPTZ``)."""
    return datetime.datetime.now(datetime.timezone.utc)


# The report endpoints (/purchases, /restock, /productreview) reject a window
# whose `to` is within the last 5 minutes ("Reports can be generated after 5
# minutes"). Clamp report windows to this lag with a small safety margin.
REPORT_LAG = datetime.timedelta(minutes=6)

# Trailing overlap window the incremental event syncs re-pull each run so late
# refunds/status changes are caught. The sync API uses the same 48h window.
TRAILING_EVENT_WINDOW = datetime.timedelta(hours=48)
# Reviews accumulate slowly; the cron default reaches back further than 48h.
REVIEW_WINDOW = datetime.timedelta(days=14)
# Timestamp format of raw-archive file names and report window labels.
ARCHIVE_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# An unquoted NULL inside a Postgres array literal is a NULL element.
ARRAY_NULL_ELEMENT = "NULL"


def clamp_report_to(window_to: datetime.datetime) -> datetime.datetime:
    """Cap a report window's upper bound to ``now - REPORT_LAG``."""
    latest = utcnow() - REPORT_LAG
    return min(window_to, latest)


def _window_label(window_from: datetime.datetime, window_to: datetime.datetime) -> str:
    window_start = window_from.strftime(ARCHIVE_STAMP_FORMAT)
    window_end = window_to.strftime(ARCHIVE_STAMP_FORMAT)
    return f"{window_start}_{window_end}"


# ===========================================================================
# Field-ownership contract (D5 requirement 1)
# ===========================================================================
#
# HUSKY_OWNED  - overwritten on every sync (the vendor is the source of truth).
# SYNC_MANAGED - bookkeeping sync writes but which is not "vendor data"
#                (is_active derived from presence, timestamps).
# LOCAL_OWNED  - NEVER touched by sync (documented for completeness; the guard
#                simply refuses any column outside HUSKY_OWNED ∪ SYNC_MANAGED).
#
# ``local_status`` (the manual override) is in LOCAL_OWNED - sync must never
# write it, so it is absent from every allowed set and the guard blocks it.

PRODUCT_HUSKY_OWNED: tuple[str, ...] = (
    "code",
    "name",
    "category_id",
    "supplier_id",
    "purchase_price",
    "sales_price",
    "vat_rate",
    "shelf_life_days",
    "description",
    "currency_code",
    "price_ex_surcharges",
)
PRODUCT_SYNC_MANAGED: tuple[str, ...] = ("is_active", "husky_synced_at", "updated_at")
PRODUCT_LOCAL_OWNED: tuple[str, ...] = ("local_status",)

FRIDGE_HUSKY_OWNED: tuple[str, ...] = (
    "husky_id",
    "husky_name",
    "friendly_name",
    "client_id",
)
FRIDGE_SYNC_MANAGED: tuple[str, ...] = ("is_active", "updated_at")
FRIDGE_LOCAL_OWNED: tuple[str, ...] = (
    "local_status",
    "delivery_address",
    "delivery_instructions",
)

FRIDGE_PRODUCT_PRICE_HUSKY_OWNED: tuple[str, ...] = (
    "sales_price",
    "price_ex_surcharges",
    "vat_rate",
    "currency_code",
)
FRIDGE_PRODUCT_PRICE_SYNC_MANAGED: tuple[str, ...] = ("updated_at",)

# Per-table set of columns an upsert's UPDATE clause is permitted to write.
_ALLOWED_UPDATE_COLUMNS: dict[str, frozenset[str]] = {
    "products": frozenset(PRODUCT_HUSKY_OWNED + PRODUCT_SYNC_MANAGED),
    "fridges": frozenset(FRIDGE_HUSKY_OWNED + FRIDGE_SYNC_MANAGED),
    "fridge_product_prices": frozenset(
        FRIDGE_PRODUCT_PRICE_HUSKY_OWNED + FRIDGE_PRODUCT_PRICE_SYNC_MANAGED
    ),
}


class SyncContractError(RuntimeError):
    """Raised when a sync upsert would write a column outside the allowed set."""


def _guarded_update_set(table_name: str, update_set: dict) -> dict:
    """Return ``update_set`` unchanged, or raise if it violates the contract.

    Enforces the master-data ownership contract at the point of every upsert:
    the UPDATE clause may only touch Husky-owned or sync-managed columns. Any
    local column (``local_status``, delivery config, ...) is rejected loudly
    rather than silently clobbered.
    """
    allowed = _ALLOWED_UPDATE_COLUMNS[table_name]
    illegal = set(update_set) - allowed
    if illegal:
        raise SyncContractError(
            f"sync upsert on {table_name} may not write local/unknown columns: "
            f"{sorted(illegal)} (allowed: {sorted(allowed)})"
        )
    return update_set


# ===========================================================================
# Effective-activity rule (D5 requirement 2)
# ===========================================================================

_STATUS_VALUES = ("active", "inactive", "cancelled", "all")


def effective_status(local_status: str | None, is_active: bool) -> str:
    """Effective status: local override wins, else Husky-derived active flag."""
    if local_status is not None:
        return local_status
    return "active" if is_active else "inactive"


def effective_status_clause(model: type, status: str | None):
    """Build a SQLAlchemy filter for ``?status=`` honouring the local override.

    * ``active``    -> no override AND Husky-active.
    * ``inactive``  -> override 'inactive', OR no override AND Husky-inactive.
    * ``cancelled`` -> override 'cancelled'.
    * ``all`` / ``None`` / unknown -> ``None`` (no filter).

    ``model`` is the ``Product`` or ``Fridge`` mapped class (both carry
    ``local_status`` and ``is_active``).
    """
    if status in (None, "all"):
        return None
    local = model.local_status
    active = model.is_active
    if status == "active":
        return and_(local.is_(None), active.is_(True))
    if status == "inactive":
        return or_(local == "inactive", and_(local.is_(None), active.is_(False)))
    if status == "cancelled":
        return local == "cancelled"
    return None


# ===========================================================================
# JobOutcome + sync_run bookkeeping
# ===========================================================================


@dataclass
class JobOutcome:
    """Result counts a sync reports back to the ``sync_run`` row."""

    fetched: int = 0
    upserted: int = 0
    blob_path: str | None = None
    skipped: int = 0
    # Tag events not representable by design (e.g. restock UNCHANGED - the
    # restock_action enum has no such value). Not data loss, tracked apart.
    unrepresentable: int = 0
    notes: list[str] = field(default_factory=list)


def create_sync_run(
    job: str,
    endpoint: str,
    window_from: datetime.datetime | None = None,
    window_to: datetime.datetime | None = None,
) -> int:
    """Insert a ``running`` ``sync_run`` row up-front and return its id.

    The sync API creates the checkpoint row synchronously (so it can return the
    id immediately) and then runs the actual sync in the background against that
    same row via ``SyncRunRecorder(run_id=...)``.
    """
    session = SessionLocal()
    try:
        run = SyncRun(
            job=job,
            endpoint=endpoint,
            window_from=window_from,
            window_to=window_to,
            status="running",
        )
        session.add(run)
        session.commit()
        return run.id
    finally:
        session.close()


class SyncRunRecorder:
    """Context manager writing/updating one ``sync_run`` row (start + finish).

    Uses its **own** session so bookkeeping survives a rollback of the sync's
    data session. When ``run_id`` is given it *adopts* a pre-created row (the API
    path) instead of inserting a new one; otherwise it inserts on ``__enter__``
    (the cron path). On an unhandled exception the row is marked ``failed``.
    """

    def __init__(
        self,
        job: str,
        endpoint: str,
        window_from: datetime.datetime | None = None,
        window_to: datetime.datetime | None = None,
        run_id: int | None = None,
    ) -> None:
        self.job = job
        self.endpoint = endpoint
        self.window_from = window_from
        self.window_to = window_to
        self._session: Session | None = None
        self._preexisting = run_id is not None
        self.run_id: int | None = run_id
        self._finished = False

    def __enter__(self) -> "SyncRunRecorder":
        self._session = SessionLocal()
        if not self._preexisting:
            run = SyncRun(
                job=self.job,
                endpoint=self.endpoint,
                window_from=self.window_from,
                window_to=self.window_to,
                status="running",
            )
            self._session.add(run)
            self._session.commit()
            self.run_id = run.id
        logger.info(
            "sync_run %s started: job=%s endpoint=%s window=%s..%s",
            self.run_id, self.job, self.endpoint, self.window_from, self.window_to,
        )
        return self

    def finish(
        self,
        status: str,
        fetched: int = 0,
        upserted: int = 0,
        blob_path: str | None = None,
        error: str | None = None,
    ) -> None:
        assert self._session is not None and self.run_id is not None
        run = self._session.get(SyncRun, self.run_id)
        if run is not None:
            run.status = status
            run.records_fetched = fetched
            run.records_upserted = upserted
            run.blob_path = blob_path
            run.error = (error or None) and error[:4000]
            run.finished_at = utcnow()
            self._session.commit()
        self._finished = True
        logger.info(
            "sync_run %s finished: status=%s fetched=%s upserted=%s",
            self.run_id, status, fetched, upserted,
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if self._session is not None:
            if exc is not None and not self._finished:
                try:
                    run = self._session.get(SyncRun, self.run_id)
                    if run is not None:
                        run.status = "failed"
                        run.error = str(exc)[:4000]
                        run.finished_at = utcnow()
                        self._session.commit()
                except Exception:  # pragma: no cover - best effort bookkeeping
                    logger.exception("failed to record sync_run failure")
            self._session.close()
        return False  # never suppress the exception


# ===========================================================================
# Reference resolvers
# ===========================================================================


def load_fridge_index(session: Session) -> dict[str, int]:
    """Map every known fridge alias (husky_id, husky_name, friendly_name) -> id."""
    index: dict[str, int] = {}
    for fridge in session.execute(select(Fridge)).scalars():
        for alias in (fridge.husky_id, fridge.husky_name, fridge.friendly_name):
            if alias:
                index[alias] = fridge.id
    return index


def load_product_index(session: Session) -> dict[str, int]:
    """Map product ``code`` -> product id."""
    return {
        code: pid
        for code, pid in session.execute(select(Product.code, Product.id))
    }


def resolve_fridge(index: dict[str, int], *candidates: str | None) -> int | None:
    """Return the first fridge id matching any candidate alias."""
    for candidate in candidates:
        if candidate and candidate in index:
            return index[candidate]
    return None


# ===========================================================================
# Product resolution with stub creation (spec 0004 rule)
# ===========================================================================

# Sentinel code for event rows that carry a tag identity but no product code.
UNKNOWN_PRODUCT_CODE = "UNKNOWN"
UNCATEGORISED_NAME = "Uncategorised"
# Category names carry their screen position as a number prefix ("10. Frozen Warm Dishes").
CATEGORY_NUMBER_PREFIX = re.compile(r"^(\d+)\.")
# Unnumbered categories, Uncategorised included, sort after every numbered one.
UNNUMBERED_CATEGORY_DISPLAY_ORDER = 999


def category_display_order(category_name: str) -> int:
    """Screen position of a category: its number prefix, else after every numbered one."""
    number_prefix = CATEGORY_NUMBER_PREFIX.match(category_name)
    if number_prefix is None:
        return UNNUMBERED_CATEGORY_DISPLAY_ORDER
    return int(number_prefix.group(1))


def effective_product_code(product_code: str | None, *tag_identity: str | None) -> str | None:
    """Decide which product code an event row resolves under.

    * payload has a code -> that code (stubbed if unknown);
    * no code but some tag identity (tagId/epc) -> :data:`UNKNOWN_PRODUCT_CODE`;
    * no code AND no tag identity -> ``None`` (row is skipped - nothing to key on).
    """
    if product_code:
        return product_code
    if any(tag_identity):
        return UNKNOWN_PRODUCT_CODE
    return None


class ProductResolver:
    """Resolve product codes to ids, creating inactive stubs for unknown codes.

    Historical purchases/restock reference discontinued products missing from
    today's catalogue. Per spec 0004, an unknown ``product_code`` CREATES A STUB
    PRODUCT (``is_active=false``, name from the payload or the code, category =
    the 'Uncategorised' row, prices from the payload else 0) instead of dropping
    the event. Created stubs are cached for the rest of the run.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._index = load_product_index(session)
        self._uncategorised_id: int | None = None
        self.stubs_created = 0

    def _uncategorised_category_id(self) -> int:
        if self._uncategorised_id is None:
            found = self._session.execute(
                select(Category.id).where(Category.name == UNCATEGORISED_NAME)
            ).scalar()
            if found is None:  # defensive - the row is expected to be seeded
                next_print = (
                    self._session.execute(
                        select(func.coalesce(func.max(Category.dispatch_print_order), 0))
                    ).scalar()
                    or 0
                ) + 1
                category = Category(
                    name=UNCATEGORISED_NAME,
                    display_order=category_display_order(UNCATEGORISED_NAME),
                    dispatch_print_order=next_print,
                )
                self._session.add(category)
                self._session.flush()
                found = category.id
            self._uncategorised_id = found
        return self._uncategorised_id

    def resolve(
        self,
        product_code: str | None,
        *,
        name: str | None = None,
        sales_price: int | None = None,  # cents (BIGINT column)
        vat_rate: Decimal | None = None,
    ) -> int | None:
        """Return the product id for ``product_code``, creating a stub if new."""
        if not product_code:
            return None
        cached = self._index.get(product_code)
        if cached is not None:
            return cached
        values: dict[str, object] = {
            "code": product_code,
            "name": name or product_code,
            "category_id": self._uncategorised_category_id(),
            "is_active": False,
        }
        if sales_price is not None:
            values["sales_price"] = sales_price
        if vat_rate is not None:
            values["vat_rate"] = vat_rate
        stmt = pg_insert(Product).values(**values).on_conflict_do_nothing(
            index_elements=["code"]
        )
        self._session.execute(stmt)
        product_id = self._session.execute(
            select(Product.id).where(Product.code == product_code)
        ).scalar()
        if product_id is None:  # pragma: no cover - conflict raced with a delete
            return None
        self._index[product_code] = product_id
        self.stubs_created += 1
        logger.info("created stub product code=%s name=%s", product_code, values["name"])
        return product_id


# ===========================================================================
# Bulk writes: COPY into a staging table, then one INSERT ... ON CONFLICT
# ===========================================================================


def copy_upsert(
    session: Session,
    target: Table,
    rows: list[dict],
    conflict_columns: list[str],
    build_update_set: Callable[[Insert], dict],
) -> int:
    """Upsert ``rows`` into ``target`` in four round trips; return the rows touched.

    The rows are streamed with COPY into a staging table, then moved with one
    ``INSERT ... SELECT ... ON CONFLICT DO UPDATE``. Every row carries the same
    keys and no two rows share a conflict key (Postgres rejects a statement that
    updates one row twice). ``build_update_set`` receives the insert statement so
    it can refer to ``excluded``. The returned count is inserted plus updated
    rows: every conflicting row counts, even when its values did not change.
    """
    if not rows:
        return 0
    column_names = list(rows[0])
    _require_same_columns(rows, column_names)
    staging_name = f"staging_{target.name}"
    quoted_staging = _quoted_identifier(staging_name)
    quoted_columns = _quoted_column_list(column_names)
    # Not LIKE target: that would copy NOT NULL id/identity columns the rows never fill.
    session.execute(
        text(
            f"CREATE TEMP TABLE {quoted_staging} AS "
            f"SELECT {quoted_columns} FROM {_quoted_identifier(target.name)} WITH NO DATA"
        )
    )
    _copy_rows_into(session, staging_name, column_names, rows)
    staging = table(staging_name, *[column(name) for name in column_names])
    insert_from_staging = pg_insert(target).from_select(column_names, select(staging))
    upsert = insert_from_staging.on_conflict_do_update(
        index_elements=conflict_columns,
        set_=build_update_set(insert_from_staging),
    )
    rows_touched = session.execute(upsert).rowcount
    # Dropped now, not ON COMMIT: one transaction may upsert the same target twice.
    session.execute(text(f"DROP TABLE {quoted_staging}"))
    return rows_touched


@contextmanager
def write_transaction(job: str) -> Iterator[Session]:
    """One short transaction for a sync's DB work, logging how long it stayed open."""
    started = time.monotonic()
    with SessionLocal() as session, session.begin():
        yield session
    logger.info("%s: write transaction open for %.2fs", job, time.monotonic() - started)


# ===========================================================================
# Catalogue sync - /facility, /fridge, /producttype, /fridgeproductprice
# ===========================================================================

_BOX_PREFIX = "box n"  # 'Box n°...' test/placeholder product types are skipped.

# Product columns the catalogue only overwrites when this run's feed carried a value.
PRODUCT_COLUMNS_WRITTEN_WHEN_PRESENT: tuple[str, ...] = (
    "supplier_id",
    "sales_price",
    "purchase_price",
    "vat_rate",
    "shelf_life_days",
    "description",
    "currency_code",
    "price_ex_surcharges",
)


@dataclass
class CatalogueFeeds:
    """Every catalogue payload, fetched and archived before any DB work starts."""

    facilities: list[FacilityItem]
    fridges: list[FridgeItem]
    product_types: list[ProductTypeItem]
    fridge_prices: list[ProductFridgeItem]


def _is_box_name(name: str | None) -> bool:
    return bool(name) and name.strip().casefold().startswith(_BOX_PREFIX)


def _get_or_create_category(
    session: Session, name: str | None, cache: dict[str, int]
) -> tuple[int, bool]:
    """Resolve a category id by name, creating one on first sight."""
    key = (name or "Uncategorised").strip() or "Uncategorised"
    if key in cache:
        return cache[key], False
    existing = session.execute(select(Category).where(Category.name == key)).scalars().first()
    if existing is not None:
        cache[key] = existing.id
        return existing.id, False
    highest_print_order = session.execute(
        select(func.coalesce(func.max(Category.dispatch_print_order), 0))
    ).scalar_one()
    category = Category(
        name=key,
        display_order=category_display_order(key),
        dispatch_print_order=highest_print_order + 1,
    )
    session.add(category)
    session.flush()
    cache[key] = category.id
    return category.id, True


def _get_or_create_supplier(
    session: Session, name: str | None, cache: dict[str, int]
) -> int | None:
    """Resolve a supplier id by ``productBrand`` name, creating one on first sight.

    The vendor's ``productBrand`` is the supplier/brand a product belongs to
    (``suppliers`` replaces the workbook's SupplierInfoTable). Names are unique;
    a blank/absent brand yields ``None`` (the product keeps its NULL supplier).
    New suppliers are created ``is_active`` by default (schema default).
    """
    key = (name or "").strip()
    if not key:
        return None
    if key in cache:
        return cache[key]
    existing = (
        session.execute(select(Supplier).where(Supplier.name == key)).scalars().first()
    )
    if existing is not None:
        cache[key] = existing.id
        return existing.id
    supplier = Supplier(name=key)
    session.add(supplier)
    session.flush()
    cache[key] = supplier.id
    return supplier.id


def sync_catalogue(run_id: int | None = None) -> JobOutcome:
    """Sync the full master catalogue (facilities, fridges, products, prices)."""
    outcome = JobOutcome()
    with SyncRunRecorder("catalogue_sync", "catalogue", run_id=run_id) as recorder:
        with HuskyClient() as client:
            feeds = _fetch_catalogue_feeds(client)
        with write_transaction("catalogue_sync") as session:
            _apply_facilities(session, feeds.facilities, outcome)
            _apply_fridges(session, feeds.fridges, outcome)
            _apply_product_types(session, feeds.product_types, outcome)
            _apply_fridge_product_prices(session, feeds.fridge_prices, outcome)
        recorder.finish(
            "success" if outcome.fetched else "empty", outcome.fetched, outcome.upserted
        )
    for note in outcome.notes:
        logger.info("%s", note)
    return outcome


def sync_prices(run_id: int | None = None) -> JobOutcome:
    """Sync only the per-fridge product prices (``/fridgeproductprice``)."""
    outcome = JobOutcome()
    with SyncRunRecorder("catalogue_sync", "fridgeproductprice", run_id=run_id) as recorder:
        with HuskyClient() as client:
            fridge_prices = _fetch_archived(client.get_fridge_product_prices, "fridgeproductprice")
        outcome.fetched = _count_price_entries(fridge_prices.fridges)
        with write_transaction("sync_prices") as session:
            _apply_fridge_product_prices(session, fridge_prices.fridges, outcome)
        recorder.finish(
            "success" if outcome.upserted else "empty", outcome.fetched, outcome.upserted
        )
    for note in outcome.notes:
        logger.info("%s", note)
    return outcome


def _fetch_catalogue_feeds(client: HuskyClient) -> CatalogueFeeds:
    facilities = _fetch_archived(client.get_facilities, "facility")
    fridges = _fetch_archived(client.get_fridges, "fridge")
    product_types = _fetch_archived(client.get_product_types, "producttype")
    fridge_prices = _fetch_archived(client.get_fridge_product_prices, "fridgeproductprice")
    return CatalogueFeeds(
        facilities=facilities.facilities,
        fridges=fridges.fridges,
        product_types=product_types.productTypes,
        fridge_prices=fridge_prices.fridges,
    )


def _fetch_archived(
    fetch_endpoint: Callable[[], FetchResult],
    archive_endpoint: str,
) -> BaseModel:
    """Call one Husky endpoint, archive its raw bytes, and return the parsed payload."""
    fetch_result = fetch_endpoint()
    archive_raw(archive_endpoint, utcnow().strftime(ARCHIVE_STAMP_FORMAT), fetch_result.raw)
    return fetch_result.data


def _apply_facilities(
    session: Session,
    facilities: list[FacilityItem],
    outcome: JobOutcome,
) -> None:
    clients_by_name = {client.name: client for client in session.execute(select(Client)).scalars()}
    fetched = 0
    for facility in facilities:
        if not facility.name:
            continue
        fetched += 1
        location_text = _facility_location_text(facility)
        existing = clients_by_name.get(facility.name)
        if existing is None:
            new_client = Client(name=facility.name, location=location_text)
            session.add(new_client)
            clients_by_name[facility.name] = new_client
        elif location_text is not None:
            existing.location = location_text
    session.flush()
    outcome.fetched += fetched
    outcome.notes.append(f"facilities->clients: {fetched}")


def _apply_fridges(session: Session, fridges: list[FridgeItem], outcome: JobOutcome) -> None:
    client_ids_by_name = {
        client.name: client.id for client in session.execute(select(Client)).scalars()
    }
    rows_by_husky_id: dict[str, dict] = {}
    fetched = 0
    for fridge in fridges:
        if not fridge.name:
            continue
        fetched += 1
        rows_by_husky_id[fridge.name] = {
            "husky_id": fridge.name,
            "husky_name": fridge.description,
            "friendly_name": fridge.friendlyName or fridge.name,
            "client_id": client_ids_by_name.get(fridge.facility),
            "is_active": True,  # present in the feed -> Husky-active
        }
    copy_upsert(
        session,
        target=Fridge.__table__,
        rows=list(rows_by_husky_id.values()),
        conflict_columns=["husky_id"],
        build_update_set=_fridge_update_set,
    )
    outcome.fetched += fetched
    outcome.upserted += fetched
    outcome.notes.append(f"fridges: {fetched}")


def _apply_product_types(
    session: Session,
    product_types: list[ProductTypeItem],
    outcome: JobOutcome,
) -> None:
    """Upsert parsed producttype items. Split from the fetch so it is testable
    without a live vendor call.
    """
    category_cache = _load_ids_by_name(session, Category)
    supplier_cache = _load_ids_by_name(session, Supplier)
    created_categories: set[str] = set()
    created_suppliers = 0
    linked_suppliers = 0
    fetched = 0
    skipped_box = 0
    rows_by_code: dict[str, dict] = {}
    now = utcnow()
    for item in product_types:
        if not item.productCode:
            continue
        if _is_box_name(item.name):
            skipped_box += 1
            continue
        fetched += 1
        category_id, created = _get_or_create_category(session, item.productCategory, category_cache)
        if created:
            created_categories.add(item.productCategory or "Uncategorised")
        supplier_count_before = len(supplier_cache)
        supplier_id = _get_or_create_supplier(session, item.productBrand, supplier_cache)
        if len(supplier_cache) > supplier_count_before:
            created_suppliers += 1
        if supplier_id is not None:
            linked_suppliers += 1
        row = {
            "code": item.productCode,
            "name": item.name or item.productCode,
            "category_id": category_id,
            "is_active": True,
            "husky_synced_at": now,
            **_present_product_values(item, supplier_id),
        }
        # A code listed twice: the later item wins column by column, as a second upsert would.
        rows_by_code.setdefault(item.productCode, {}).update(row)

    _upsert_products(session, list(rows_by_code.values()))

    # Products previously synced from Husky but absent now -> deactivate (never
    # delete, never touch local_status). Restricted to husky-sourced rows so
    # manual/seed products survive.
    deactivated = 0
    seen_codes = list(rows_by_code)
    if seen_codes:
        deactivation = session.execute(
            update(Product)
            .where(
                Product.husky_synced_at.is_not(None),
                Product.code.not_in(seen_codes),
                Product.is_active.is_(True),
            )
            .values(is_active=False, updated_at=func.now())
        )
        deactivated = deactivation.rowcount

    outcome.fetched += fetched
    outcome.upserted += fetched
    outcome.skipped += skipped_box
    outcome.notes.append(
        f"producttypes: upserted={fetched} skipped_box={skipped_box} deactivated={deactivated}"
    )
    outcome.notes.append(
        f"suppliers: created={created_suppliers} product_links={linked_suppliers}"
    )
    if created_categories:
        outcome.notes.append(
            "AUTO-CREATED categories (Husky names not in seeded taxonomy): "
            + ", ".join(sorted(created_categories))
        )


def _apply_fridge_product_prices(
    session: Session,
    fridge_prices: list[ProductFridgeItem],
    outcome: JobOutcome,
) -> None:
    fridge_index = load_fridge_index(session)
    product_index = load_product_index(session)
    rows_by_fridge_product: dict[tuple[int, int], dict] = {}
    upserted = 0
    unresolved = 0
    for fridge_entry in fridge_prices:
        fridge_id = resolve_fridge(fridge_index, fridge_entry.name, fridge_entry.friendlyName)
        if fridge_id is None:
            unresolved += 1
            continue
        for price in fridge_entry.prices:
            product_id = product_index.get(price.productCode)
            if product_id is None or price.price is None:
                unresolved += 1
                continue
            upserted += 1
            row = {
                "fridge_id": fridge_id,
                "product_id": product_id,
                "sales_price": price.price,  # raw cents (BIGINT column)
                "price_ex_surcharges": price.priceExSurcharges,
                "vat_rate": normalize_vat_fraction(price.vat),
                "currency_code": price.currencyCode or None,
            }
            row_key = (fridge_id, product_id)
            earlier_row = rows_by_fridge_product.get(row_key)
            if earlier_row is not None:
                row = _merge_present_values(earlier_row, row)
            rows_by_fridge_product[row_key] = row
    copy_upsert(
        session,
        target=FridgeProductPrice.__table__,
        rows=list(rows_by_fridge_product.values()),
        conflict_columns=["fridge_id", "product_id"],
        build_update_set=_fridge_price_update_set,
    )
    outcome.upserted += upserted
    outcome.notes.append(f"fridge_product_prices: upserted={upserted} unresolved={unresolved}")


def _count_price_entries(fridge_prices: list[ProductFridgeItem]) -> int:
    price_entry_count = 0
    for fridge_entry in fridge_prices:
        price_entry_count += len(fridge_entry.prices)
    return price_entry_count


def _facility_location_text(facility: FacilityItem) -> str | None:
    if facility.location is None:
        return None
    parts = [
        facility.location.address,
        facility.location.zipPostalCode,
        facility.location.city,
        facility.location.countryCode,
    ]
    return ", ".join(part for part in parts if part) or None


def _fridge_update_set(upsert: Insert) -> dict:
    """Fridge columns a catalogue sync refreshes.

    Only Husky-owned and sync-managed columns: local_status and delivery_* are
    never written. ``client_id`` is COALESCE(stored, feed) on purpose (tracker
    item A4): a client assigned by hand survives every Husky refresh, and the
    facility's client only fills a fridge that has none yet.
    """
    return _guarded_update_set(
        "fridges",
        {
            "husky_name": upsert.excluded.husky_name,
            "friendly_name": upsert.excluded.friendly_name,
            "client_id": func.coalesce(Fridge.client_id, upsert.excluded.client_id),
            "is_active": upsert.excluded.is_active,
            "updated_at": func.now(),
        },
    )


def _load_ids_by_name(
    session: Session,
    model: type[Category] | type[Supplier],
) -> dict[str, int]:
    """Map each stored name, stripped like the get-or-create lookups strip it, to its id."""
    named_rows = session.execute(select(model.name, model.id))
    return {name.strip(): row_id for name, row_id in named_rows}


def _present_product_values(item: ProductTypeItem, supplier_id: int | None) -> dict:
    """The optional product columns this item carries; absent ones keep the stored value."""
    shelf_life = item.expiryDays if (item.expiryDays and item.expiryDays > 0) else None
    optional_values = {
        "supplier_id": supplier_id,
        # Vendor int64 minor units (cents) stored RAW (BIGINT column). A price of 0
        # means "not priced": fall back to priceExSurcharges, else keep the stored price.
        "sales_price": item.price or item.priceExSurcharges or None,
        # BUY price: `reference` is a euro DECIMAL STRING (e.g. "5.95"), NOT
        # integer cents like `price`. Scale euros -> cents for the BIGINT column.
        "purchase_price": euros_to_minor_units(item.reference),
        "vat_rate": normalize_vat_fraction(item.vat),
        "shelf_life_days": shelf_life,
        "description": item.description or None,
        "currency_code": item.currencyCode or None,
        "price_ex_surcharges": item.priceExSurcharges,
    }
    return {name: value for name, value in optional_values.items() if value is not None}


def _upsert_products(session: Session, rows: list[dict]) -> None:
    """Upsert products, one statement per set of columns the feed carried.

    A column the feed left out stays out of the INSERT (the server default
    applies to a new product) and out of the UPDATE (an existing product keeps
    its value), so a manually-entered price is never clobbered by a default.
    """
    rows_by_column_set: dict[frozenset[str], list[dict]] = defaultdict(list)
    for row in rows:
        rows_by_column_set[frozenset(row)].append(row)
    for column_set, rows_with_same_columns in rows_by_column_set.items():
        copy_upsert(
            session,
            target=Product.__table__,
            rows=rows_with_same_columns,
            conflict_columns=["code"],
            build_update_set=partial(_product_update_set, present_columns=column_set),
        )


def _product_update_set(upsert: Insert, present_columns: frozenset[str]) -> dict:
    # Contract: only Husky-owned + sync-managed columns. local_status is
    # NEVER written, so a manual override survives every catalogue sync.
    update_set = {
        "name": upsert.excluded.name,
        "category_id": upsert.excluded.category_id,
        "is_active": True,
        "husky_synced_at": upsert.excluded.husky_synced_at,
        "updated_at": func.now(),
    }
    for column_name in PRODUCT_COLUMNS_WRITTEN_WHEN_PRESENT:
        if column_name in present_columns:
            update_set[column_name] = upsert.excluded[column_name]
    return _guarded_update_set("products", update_set)


def _fridge_price_update_set(upsert: Insert) -> dict:
    excluded = upsert.excluded
    # Only overwrite a stored extra when this run's feed carried a value for it.
    return _guarded_update_set(
        "fridge_product_prices",
        {
            "sales_price": excluded.sales_price,
            "price_ex_surcharges": func.coalesce(
                excluded.price_ex_surcharges,
                FridgeProductPrice.price_ex_surcharges,
            ),
            "vat_rate": func.coalesce(excluded.vat_rate, FridgeProductPrice.vat_rate),
            "currency_code": func.coalesce(
                excluded.currency_code,
                FridgeProductPrice.currency_code,
            ),
            "updated_at": func.now(),
        },
    )


def _merge_present_values(earlier_row: dict, later_row: dict) -> dict:
    """Later values win, but a value the later row lacks (None) keeps the earlier one."""
    merged_row = dict(earlier_row)
    for column_name, value in later_row.items():
        if value is not None:
            merged_row[column_name] = value
    return merged_row


def backfill_supplier_links_from_archive() -> JobOutcome:
    """Link still-unlinked products to suppliers using the producttype archives.

    The live catalogue sync only links products present in *today's* feed.
    Historical/inactive stub products (discontinued codes no longer in the feed)
    keep a NULL ``supplier_id``. This scans every archived ``producttype`` payload
    for a ``productCode -> productBrand`` mapping, creates any missing suppliers,
    and sets ``supplier_id`` on products that are still NULL. Idempotent and
    read-only against the vendor (archive files only).
    """
    outcome = JobOutcome()
    settings = get_settings()
    archive_dir = Path(settings.raw_archive_dir) / "raw" / "husky" / "producttype"
    code_to_brand: dict[str, str] = {}
    files = sorted(archive_dir.rglob("*.json.gz")) if archive_dir.exists() else []
    for path in files:
        try:
            payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        except (OSError, ValueError):  # skip a corrupt/partial archive file
            continue
        for item in payload.get("productTypes", []):
            code = item.get("productCode")
            brand = (item.get("productBrand") or "").strip()
            if code and brand:
                code_to_brand[code] = brand  # later archives win (freshest brand)
    outcome.fetched = len(code_to_brand)
    if not code_to_brand:
        outcome.notes.append("backfill_supplier_links: no archived producttype brands")
        return outcome

    session = SessionLocal()
    try:
        supplier_cache: dict[str, int] = {}
        linked = 0
        for code, brand in code_to_brand.items():
            supplier_id = _get_or_create_supplier(session, brand, supplier_cache)
            if supplier_id is None:
                continue
            result = session.execute(
                update(Product)
                .where(Product.code == code, Product.supplier_id.is_(None))
                .values(supplier_id=supplier_id, updated_at=func.now())
            )
            linked += result.rowcount or 0
        session.commit()
        outcome.upserted = linked
        outcome.notes.append(
            f"backfill_supplier_links: suppliers={len(supplier_cache)} products_linked={linked}"
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    for note in outcome.notes:
        logger.info("%s", note)
    return outcome


# ===========================================================================
# Purchases -> sales_events
# ===========================================================================


def _build_purchase_rows(
    result_fridges: dict,
    fridge_index: dict[str, int],
    products: ProductResolver,
    outcome: JobOutcome,
) -> dict[tuple[str, datetime.datetime], dict]:
    rows: dict[tuple[str, datetime.datetime], dict] = {}
    for fridge_key, fridge in result_fridges.items():
        fridge_id = resolve_fridge(fridge_index, fridge_key, fridge.name, fridge.friendlyName)
        if fridge_id is None:
            outcome.skipped += 1
            continue
        for purchase in fridge.purchases:
            sold_at = purchase.purchaseDate
            if sold_at is None:
                outcome.skipped += 1
                continue
            for index, product in enumerate(purchase.products):
                unit_price = product.price
                if unit_price is None:
                    unit_price = product.priceExSurcharges or 0
                code = effective_product_code(product.productCode, product.tagId, product.epc)
                product_id = products.resolve(
                    code,
                    name=product.name,
                    sales_price=unit_price,
                    vat_rate=normalize_vat_fraction(product.vat),
                )
                if product_id is None:
                    outcome.skipped += 1
                    continue
                husky_ref = product.tagId or f"{purchase.id}:{product.epc or index}"
                rows[(husky_ref, sold_at)] = {
                    "husky_ref": husky_ref,
                    "fridge_id": fridge_id,
                    "product_id": product_id,
                    "sold_at": sold_at,
                    "unit_price": unit_price,
                    "is_refunded": is_refunded(product.refundStatus),
                    "discount_amount": sum_discount_minor_units(product.discounts),
                    "discount_provider": first_discount_provider(product.discounts),
                }
    return rows


def _upsert_sales_events(session: Session, rows: list[dict]) -> int:
    return copy_upsert(
        session,
        target=SalesEvent.__table__,
        rows=rows,
        conflict_columns=["husky_ref", "sold_at"],
        build_update_set=_sales_event_update_set,
    )


def _sales_event_update_set(upsert: Insert) -> dict:
    return {
        "fridge_id": upsert.excluded.fridge_id,
        "product_id": upsert.excluded.product_id,
        "unit_price": upsert.excluded.unit_price,
        "is_refunded": upsert.excluded.is_refunded,
        "discount_amount": upsert.excluded.discount_amount,
        "discount_provider": upsert.excluded.discount_provider,
        "synced_at": utcnow(),
    }


def sync_purchases_window(
    window_from: datetime.datetime | None = None,
    window_to: datetime.datetime | None = None,
    run_id: int | None = None,
) -> JobOutcome:
    now = utcnow()
    window_to = clamp_report_to(window_to or now)
    window_from = window_from or (window_to - TRAILING_EVENT_WINDOW)
    outcome = JobOutcome()
    with SyncRunRecorder("sync_purchases", "purchases", window_from, window_to, run_id=run_id) as recorder:
        with HuskyClient() as client:
            fetch = client.get_purchases(window_from, window_to)
        blob = archive_raw("purchases", _window_label(window_from, window_to), fetch.raw)
        with write_transaction("sync_purchases") as session:
            fridge_index = load_fridge_index(session)
            products = ProductResolver(session)
            rows_map = _build_purchase_rows(fetch.data.fridges, fridge_index, products, outcome)
            if products.stubs_created:
                outcome.notes.append(f"stub_products_created={products.stubs_created}")
            rows = list(rows_map.values())
            outcome.fetched = len(rows) + outcome.skipped
            outcome.upserted = _upsert_sales_events(session, rows)
        outcome.blob_path = str(blob)
        recorder.finish(
            "success" if outcome.upserted else "empty",
            outcome.fetched, outcome.upserted, outcome.blob_path,
        )
    logger.info("purchases: fetched=%s upserted=%s skipped=%s", outcome.fetched, outcome.upserted, outcome.skipped)
    return outcome


# ===========================================================================
# Restock -> restock_events
# ===========================================================================

_ACTION_MAP = {"ADDED": "added", "REMOVED": "removed"}
_STATUS_MAP = {"VALID": "valid", "UNRELIABLE": "unreliable", "UNRECOGNISED": "unrecognised"}


def _build_restock_rows(
    sessions: dict,
    fridge_index: dict[str, int],
    products: ProductResolver,
    outcome: JobOutcome,
) -> dict[tuple[str, datetime.datetime], dict]:
    rows: dict[tuple[str, datetime.datetime], dict] = {}
    for session_key, restock in sessions.items():
        occurred_at = restock.endDate or restock.startDate or restock.reportingDate
        if occurred_at is None:
            outcome.skipped += 1
            continue
        fridge = restock.fridge
        fridge_id = None
        if fridge is not None:
            fridge_id = resolve_fridge(fridge_index, fridge.name, fridge.friendlyName)
        if fridge_id is None:
            outcome.skipped += 1
            continue
        for index, tag in enumerate(restock.tags):
            action = _ACTION_MAP.get((tag.action or "").upper())
            if action is None:  # UNCHANGED or unknown - not representable.
                outcome.unrepresentable += 1
                continue
            code = effective_product_code(tag.productCode, tag.tagId, tag.epc)
            product_id = products.resolve(code, name=tag.productName)
            if product_id is None:
                outcome.skipped += 1
                continue
            husky_ref = tag.tagId or f"{session_key}:{tag.epc or index}"
            tag_status = _STATUS_MAP.get((tag.status or "VALID").upper(), "valid")
            rows[(husky_ref, occurred_at)] = {
                "husky_ref": husky_ref,
                "fridge_id": fridge_id,
                "product_id": product_id,
                "action": action,
                "tag_status": tag_status,
                "occurred_at": occurred_at,
            }
    return rows


def _upsert_restock_events(session: Session, rows: list[dict]) -> int:
    return copy_upsert(
        session,
        target=RestockEvent.__table__,
        rows=rows,
        conflict_columns=["husky_ref", "occurred_at"],
        build_update_set=_restock_event_update_set,
    )


def _restock_event_update_set(upsert: Insert) -> dict:
    return {
        "fridge_id": upsert.excluded.fridge_id,
        "product_id": upsert.excluded.product_id,
        "action": upsert.excluded.action,
        "tag_status": upsert.excluded.tag_status,
        "synced_at": utcnow(),
    }


def sync_restock_window(
    window_from: datetime.datetime | None = None,
    window_to: datetime.datetime | None = None,
    run_id: int | None = None,
) -> JobOutcome:
    now = utcnow()
    window_to = clamp_report_to(window_to or now)
    window_from = window_from or (window_to - TRAILING_EVENT_WINDOW)
    outcome = JobOutcome()
    with SyncRunRecorder("sync_restock", "restock", window_from, window_to, run_id=run_id) as recorder:
        with HuskyClient() as client:
            fetch = client.get_restock(window_from, window_to)
        blob = archive_raw("restock", _window_label(window_from, window_to), fetch.raw)
        with write_transaction("sync_restock") as session:
            fridge_index = load_fridge_index(session)
            products = ProductResolver(session)
            rows_map = _build_restock_rows(fetch.data.sessions, fridge_index, products, outcome)
            if products.stubs_created:
                outcome.notes.append(f"stub_products_created={products.stubs_created}")
            rows = list(rows_map.values())
            outcome.fetched = len(rows) + outcome.skipped
            outcome.upserted = _upsert_restock_events(session, rows)
        outcome.blob_path = str(blob)
        recorder.finish(
            "success" if outcome.upserted else "empty",
            outcome.fetched, outcome.upserted, outcome.blob_path,
        )
    logger.info(
        "restock: fetched=%s upserted=%s skipped=%s unchanged_unrepresentable=%s",
        outcome.fetched, outcome.upserted, outcome.skipped, outcome.unrepresentable,
    )
    return outcome


# ===========================================================================
# Product reviews -> product_reviews
# ===========================================================================


def _synth_review_ref(
    product_code: str,
    fridge_name: str | None,
    reviewed_at: datetime.datetime,
    rating: int,
    purchase_id: str | None,
) -> str:
    return f"{product_code}|{fridge_name or ''}|{reviewed_at.isoformat()}|{rating}|{purchase_id or ''}"


def _build_review_rows(
    reviews: list[ProductReviewItem],
    fridge_index: dict[str, int],
    products: ProductResolver,
    outcome: JobOutcome,
) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for review in reviews:
        product = review.product
        product_code = effective_product_code(
            product.productCode if product else None,
            product.tagId if product else None,
            product.epc if product else None,
        )
        product_id = products.resolve(
            product_code,
            name=product.name if product else None,
        )
        reviewed_at = review.reviewDate
        if product_id is None or reviewed_at is None or review.rating is None:
            outcome.skipped += 1
            continue
        fridge_name = review.fridge.name if review.fridge else None
        fridge_id = resolve_fridge(
            fridge_index,
            fridge_name,
            review.fridge.friendlyName if review.fridge else None,
        )
        ref = _synth_review_ref(
            product_code,
            fridge_name,
            reviewed_at,
            review.rating,
            review.purchaseId,
        )
        rows[ref] = {
            "husky_ref": ref,
            "product_id": product_id,
            "fridge_id": fridge_id,
            "rating": review.rating,
            "reviewed_at": reviewed_at,
            # Extra Husky fields retained store-only (see migration 0010).
            "review_text": review.review or None,
            "reviewer_email": review.userEmailAddress or None,
            "purchase_id": review.purchaseId or None,
            "purchased_at": review.purchaseDate,
            "review_category": review.category or None,
            "tag_id": product.tagId if product else None,
            "epc": product.epc if product else None,
            "product_reference": product.reference if product else None,
        }
    return rows


def _upsert_reviews(session: Session, rows: list[dict]) -> int:
    return copy_upsert(
        session,
        target=ProductReview.__table__,
        rows=rows,
        conflict_columns=["husky_ref"],
        build_update_set=_review_update_set,
    )


def _review_update_set(upsert: Insert) -> dict:
    return {
        "product_id": upsert.excluded.product_id,
        "fridge_id": upsert.excluded.fridge_id,
        "rating": upsert.excluded.rating,
        "reviewed_at": upsert.excluded.reviewed_at,
        "review_text": upsert.excluded.review_text,
        "reviewer_email": upsert.excluded.reviewer_email,
        "purchase_id": upsert.excluded.purchase_id,
        "purchased_at": upsert.excluded.purchased_at,
        "review_category": upsert.excluded.review_category,
        "tag_id": upsert.excluded.tag_id,
        "epc": upsert.excluded.epc,
        "product_reference": upsert.excluded.product_reference,
        "synced_at": utcnow(),
    }


def sync_reviews_window(
    window_from: datetime.datetime | None = None,
    window_to: datetime.datetime | None = None,
    run_id: int | None = None,
) -> JobOutcome:
    now = utcnow()
    window_to = clamp_report_to(window_to or now)
    window_from = window_from or (window_to - REVIEW_WINDOW)
    outcome = JobOutcome()
    with SyncRunRecorder("reviews_sync", "productreview", window_from, window_to, run_id=run_id) as recorder:
        with HuskyClient() as client:
            fetch = client.get_product_reviews(window_from, window_to)
        blob = archive_raw("productreview", _window_label(window_from, window_to), fetch.raw)
        with write_transaction("reviews_sync") as session:
            fridge_index = load_fridge_index(session)
            products = ProductResolver(session)
            rows_map = _build_review_rows(
                fetch.data.productReviews,
                fridge_index,
                products,
                outcome,
            )
            if products.stubs_created:
                outcome.notes.append(f"stub_products_created={products.stubs_created}")
            rows = list(rows_map.values())
            outcome.fetched = len(rows) + outcome.skipped
            outcome.upserted = _upsert_reviews(session, rows)
        outcome.blob_path = str(blob)
        recorder.finish(
            "success" if outcome.upserted else "empty",
            outcome.fetched, outcome.upserted, outcome.blob_path,
        )
    logger.info("reviews: fetched=%s upserted=%s skipped=%s", outcome.fetched, outcome.upserted, outcome.skipped)
    return outcome


# ===========================================================================
# Stock snapshot -> fridge_stock (latest-only, mark-and-sweep)
# ===========================================================================
# fridge_stock holds ONE row per (fridge, product): the latest known in-fridge
# stock, not a time series. Each run stamps a single shared ``taken_at`` on every
# row it upserts (the "generation"), then sweeps away the older-generation rows
# OF THE FRIDGES IT REPORTED ON, so the table mirrors the last /stock/current
# response for exactly those fridges.
# Without the sweep, a product pulled out of a fridge would keep its last
# units > 0 row forever and the allocation engine would under-dispatch it.
# The sweep is SCOPED to the fridges present in the payload: a partial vendor
# response (3 of 47 fridges) must never wipe the 44 fridges it said nothing
# about - they would then read as live = 0 and every one would be over-dispatched
# to full target. A fridge absent from the payload keeps its rows with their OLD
# taken_at, which is precisely the signal the allocation reader uses to flag it
# stale (see menu_allocation_service.STOCK_READING_MAX_AGE).
# Upsert + sweep run in the SAME transaction, so a reader never sees a
# half-swept table.


@dataclass
class StockSnapshotRows:
    """The fridge_stock rows of one payload and every known fridge it reported on."""

    rows: dict[tuple[int, str], dict] = field(default_factory=dict)
    # Includes fridges reported with no products: all their old rows must be swept.
    reported_fridge_ids: set[int] = field(default_factory=set)


def _build_stock_rows(
    stock_entries: list[CurrentStock],
    fridge_index: dict[str, int],
    product_index: dict[str, int],
    taken_at: datetime.datetime,
    outcome: JobOutcome,
) -> StockSnapshotRows:
    snapshot = StockSnapshotRows()
    for entry in stock_entries:
        fridge = entry.fridge
        fridge_id = None
        if fridge is not None:
            fridge_id = resolve_fridge(fridge_index, fridge.name, fridge.friendlyName)
        if fridge_id is None:
            outcome.skipped += 1
            continue
        snapshot.reported_fridge_ids.add(fridge_id)
        for product in entry.products:
            if not product.productCode:
                outcome.skipped += 1
                continue
            snapshot.rows[(fridge_id, product.productCode)] = {
                "taken_at": taken_at,
                "fridge_id": fridge_id,
                "product_id": product_index.get(product.productCode),
                "product_code": product.productCode,
                "units": len(product.current),
                # Per-tag expiry dates (Husky sets them from the product
                # shelf life at restock); tags without one are omitted, so
                # `units` stays the authoritative count. Feeds the forecast
                # residual-stock deduction + the withdrawal list. getattr
                # keeps it safe if a tag is a bare id rather than a StockTag.
                "expiry_dates": [
                    expiry
                    for tag in product.current
                    if (expiry := getattr(tag, "expiryDate", None)) is not None
                ],
            }
    return snapshot


def _upsert_fridge_stock(session: Session, rows: list[dict]) -> int:
    return copy_upsert(
        session,
        target=FridgeStock.__table__,
        rows=rows,
        conflict_columns=["fridge_id", "product_code"],
        build_update_set=_fridge_stock_update_set,
    )


def _fridge_stock_update_set(upsert: Insert) -> dict:
    return {
        "product_id": upsert.excluded.product_id,
        "units": upsert.excluded.units,
        "expiry_dates": upsert.excluded.expiry_dates,
        "taken_at": upsert.excluded.taken_at,
    }


def _sweep_fridge_stock(
    session: Session, taken_at: datetime.datetime, fridge_ids: set[int]
) -> int:
    """Delete the rows of the REPORTED fridges that this run did not rewrite.

    ``fridge_ids`` are the fridges present in the payload that stamped
    ``taken_at``. Fridges outside that set are left alone on purpose (see the
    section comment): their retained old generation is the offline signal.
    """
    if not fridge_ids:
        return 0
    result = session.execute(
        delete(FridgeStock).where(
            FridgeStock.taken_at < taken_at,
            FridgeStock.fridge_id.in_(fridge_ids),
        )
    )
    return result.rowcount or 0


def snapshot_stock(
    taken_at: datetime.datetime | None = None,
    run_id: int | None = None,
) -> JobOutcome:
    taken_at = taken_at or utcnow()
    outcome = JobOutcome()
    with SyncRunRecorder("snapshot_stock", "stock_current", taken_at, taken_at, run_id=run_id) as recorder:
        with HuskyClient() as client:
            fetch = client.get_stock_current()
        blob = archive_raw("stock_current", taken_at.strftime(ARCHIVE_STAMP_FORMAT), fetch.raw)
        with write_transaction("snapshot_stock") as session:
            fridge_index = load_fridge_index(session)
            product_index = load_product_index(session)
            snapshot = _build_stock_rows(
                fetch.data.current,
                fridge_index,
                product_index,
                taken_at,
                outcome,
            )
            row_list = list(snapshot.rows.values())
            outcome.fetched = len(row_list) + outcome.skipped
            outcome.upserted = _upsert_fridge_stock(session, row_list)
            # The sweep only ever touches the fridges THIS payload reported on,
            # including a reported fridge that is now empty.
            reported_fridge_ids = snapshot.reported_fridge_ids
            # A payload with no known fridge means a vendor problem, NOT "every
            # fridge is empty": nothing is swept.
            if reported_fridge_ids:
                swept = _sweep_fridge_stock(session, taken_at, reported_fridge_ids)
            else:
                swept = 0
                logger.warning(
                    "stock snapshot @%s reported no known fridge (skipped=%s) - sweep "
                    "skipped, fridge_stock left untouched",
                    taken_at, outcome.skipped,
                )
            outcome.notes.append(
                f"fridge_stock: upserted={outcome.upserted} swept={swept} "
                f"fridges_reported={len(reported_fridge_ids)}"
            )
        outcome.blob_path = str(blob)
        recorder.finish(
            "success" if outcome.upserted else "empty",
            outcome.fetched, outcome.upserted, outcome.blob_path,
        )
    logger.info(
        "stock snapshot @%s: fetched=%s upserted=%s swept=%s skipped=%s",
        taken_at, outcome.fetched, outcome.upserted, swept, outcome.skipped,
    )
    return outcome


# ===========================================================================
# Combined "all" feed
# ===========================================================================


def sync_all(run_id: int | None = None) -> JobOutcome:
    """Run every feed sequentially under one umbrella ``sync_run`` row.

    Each child sync writes its own ``sync_run`` row; the umbrella row (``run_id``)
    is finished with the aggregate fetched/upserted counts. A failure in any
    child fails the umbrella (child rows already record their own status).
    """
    aggregate = JobOutcome()
    with SyncRunRecorder("sync_all", "all", run_id=run_id) as recorder:
        for step in (
            sync_catalogue,
            sync_purchases_window,
            sync_restock_window,
            sync_reviews_window,
            snapshot_stock,
        ):
            child = step()
            aggregate.fetched += child.fetched
            aggregate.upserted += child.upserted
            aggregate.skipped += child.skipped
            aggregate.notes.append(f"{step.__name__}: fetched={child.fetched} upserted={child.upserted}")
        recorder.finish(
            "success" if aggregate.fetched else "empty",
            aggregate.fetched, aggregate.upserted,
        )
    return aggregate


def _copy_rows_into(
    session: Session,
    staging_name: str,
    column_names: list[str],
    rows: list[dict],
) -> None:
    """Stream ``rows`` into the staging table with COPY on the session's own connection."""
    csv_buffer = io.StringIO()
    # QUOTE_NOTNULL leaves None as an unquoted empty field, which COPY csv reads as
    # NULL, and quotes every other value, so an empty string stays an empty string.
    writer = csv.writer(csv_buffer, quoting=csv.QUOTE_NOTNULL, lineterminator="\n")
    for row in rows:
        writer.writerow([_copy_text(row[column_name]) for column_name in column_names])
    csv_buffer.seek(0)
    quoted_staging = _quoted_identifier(staging_name)
    quoted_columns = _quoted_column_list(column_names)
    copy_sql = f"COPY {quoted_staging} ({quoted_columns}) FROM STDIN WITH (FORMAT csv)"
    driver_connection = session.connection().connection.driver_connection
    with driver_connection.cursor() as cursor:
        cursor.copy_expert(copy_sql, csv_buffer)


def _copy_text(value: object) -> str | None:
    """Render one value as the text Postgres parses for its column type."""
    if value is None:
        return None
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, list):
        return _postgres_array_literal(value)
    return str(value)


def _postgres_array_literal(values: list) -> str:
    element_texts = []
    for value in values:
        if value is None:
            element_texts.append(ARRAY_NULL_ELEMENT)
            continue
        escaped = _copy_text(value).replace("\\", "\\\\").replace('"', '\\"')
        element_texts.append(f'"{escaped}"')
    return "{" + ",".join(element_texts) + "}"


def _require_same_columns(rows: list[dict], column_names: list[str]) -> None:
    expected_columns = set(column_names)
    for row_number, row in enumerate(rows):
        if set(row) != expected_columns:
            raise ValueError(
                f"copy_upsert row {row_number} has columns {sorted(row)}, "
                f"expected {sorted(expected_columns)}"
            )


def _quoted_identifier(name: str) -> str:
    escaped_name = name.replace('"', '""')
    return f'"{escaped_name}"'


def _quoted_column_list(column_names: list[str]) -> str:
    quoted_names = [_quoted_identifier(name) for name in column_names]
    return ", ".join(quoted_names)
