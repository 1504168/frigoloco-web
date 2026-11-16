"""Database side of the history import: master-data lookup, replace-mode writes, reconciliation.

Imported rows are marked by ``created_by`` = a dedicated, login-less system user
(``IMPORT_USER_EMAIL``). A re-import replaces only rows carrying that marker; a
dispatch or PO the app created at the same delivery date / order number is a
collision and is left untouched.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import insert, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session

from app.db import engine
from app.models.enums import UserRole
from app.models.master import Fridge, ProductTarget, User
from app.models.operations import Dispatch, DispatchLine, PurchaseOrder, PurchaseOrderLine
from scripts.history_import.plan import (
    PLACEHOLDER_FRIDGE_HUSKY_IDS,
    Catalogue,
    CatalogueProduct,
    ImportPlan,
    PlannedDispatch,
    PlannedOrder,
    highest_order_sequence_by_year,
)

IMPORT_USER_EMAIL = "excel-history-import@frigoloco.invalid"
IMPORT_USER_FULL_NAME = "Excel history import (system, no login)"
# Not a bcrypt hash, so verify_password() can never match it; the user is also inactive.
UNUSABLE_PASSWORD_HASH = "!"
PLACEHOLDER_LOCAL_STATUS = "inactive"
LINE_INSERT_CHUNK_SIZE = 5000
EXCEL_TIMEZONE_NAME = "Europe/Brussels"


class ExistingAction(StrEnum):
    REPLACE = "replace"
    COLLISION = "collision"


@dataclass(frozen=True)
class ExistingRecord:
    """A dispatch or PO already in the DB at a key the workbook also has."""

    id: int
    key: str
    status: str
    is_imported: bool
    line_count: int
    stock_movement_count: int


@dataclass(frozen=True)
class Collision:
    kind: str
    record: ExistingRecord


@dataclass
class WriteSummary:
    dispatches_inserted: int = 0
    dispatches_replaced: int = 0
    dispatch_lines_inserted: int = 0
    orders_inserted: int = 0
    orders_replaced: int = 0
    order_lines_inserted: int = 0
    targets_inserted: int = 0
    targets_updated: int = 0
    placeholder_fridges_created: list[str] = field(default_factory=list)
    collisions: list[Collision] = field(default_factory=list)
    order_counters_before: dict[int, int] = field(default_factory=dict)
    order_counters_after: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RestockWeek:
    week_start: datetime.date
    added_units: int
    removed_units: int


def load_catalogue(session: Session) -> Catalogue:
    products_by_code: dict[str, CatalogueProduct] = {}
    product_ids_by_name: dict[str, list[int]] = {}
    product_rows = session.execute(
        text("SELECT id, code, name, purchase_price, sales_price, vat_rate FROM products")
    )
    for product_row in product_rows:
        products_by_code[product_row.code] = CatalogueProduct(
            id=product_row.id,
            purchase_price=product_row.purchase_price,
            sales_price=product_row.sales_price,
            vat_rate=product_row.vat_rate,
        )
        name_key = product_row.name.strip().lower()
        product_ids_by_name.setdefault(name_key, []).append(product_row.id)
    fridge_names = set(session.scalars(text("SELECT friendly_name FROM fridges")))
    supplier_rows = session.execute(text("SELECT id, name FROM suppliers"))
    supplier_id_by_name = {supplier.name: supplier.id for supplier in supplier_rows}
    return Catalogue(
        products_by_code=products_by_code,
        product_ids_by_name=product_ids_by_name,
        fridge_names=fridge_names,
        supplier_id_by_name=supplier_id_by_name,
    )


def classify_existing(record: ExistingRecord) -> ExistingAction:
    """Only an imported row with no stock movements may be deleted and re-imported."""
    if record.is_imported and record.stock_movement_count == 0:
        return ExistingAction.REPLACE
    return ExistingAction.COLLISION


def ensure_dispatch_partitions(plan: ImportPlan) -> None:
    """Create any missing monthly dispatch_lines partition (idempotent DDL).

    Runs on its own connection: the DDL lock is released at once, and the import
    transaction stays fully roll-back-able for a dry run.
    """
    month_starts = sorted({dispatch.delivery_date.replace(day=1) for dispatch in plan.dispatches})
    with engine.begin() as connection:
        for month_start in month_starts:
            connection.execute(
                text("SELECT create_dispatch_line_partition_for_month(:month_start)"),
                {"month_start": month_start},
            )


def write_plan(session: Session, plan: ImportPlan, catalogue: Catalogue) -> WriteSummary:
    """Apply the plan inside the caller's transaction; the caller commits or rolls back."""
    summary = WriteSummary()
    import_user_id = _get_or_create_import_user(session)
    summary.placeholder_fridges_created = _create_placeholder_fridges(session, plan, catalogue)
    fridge_rows = session.execute(text("SELECT friendly_name, id FROM fridges"))
    fridge_id_by_name = {fridge.friendly_name: fridge.id for fridge in fridge_rows}
    _write_dispatches(session, plan, import_user_id, fridge_id_by_name, summary)
    _write_orders(session, plan, import_user_id, summary)
    _write_targets(session, plan, fridge_id_by_name, summary)
    _raise_order_counters(session, plan, summary)
    return summary


def load_weekly_restock_units(
    session: Session,
    first_day: datetime.date,
    last_day: datetime.date,
) -> list[RestockWeek]:
    """Husky restock tag events per Brussels ISO week (one event = one unit)."""
    week_rows = session.execute(
        text(
            """
            SELECT date_trunc('week', occurred_at AT TIME ZONE :timezone)::date AS week_start,
                   count(*) FILTER (WHERE action = 'added') AS added_units,
                   count(*) FILTER (WHERE action = 'removed') AS removed_units
            FROM restock_events
            WHERE occurred_at >= (CAST(:first_day AS timestamp) AT TIME ZONE :timezone)
              AND occurred_at < (CAST(:day_after_last AS timestamp) AT TIME ZONE :timezone)
            GROUP BY 1
            ORDER BY 1
            """
        ),
        {
            "timezone": EXCEL_TIMEZONE_NAME,
            "first_day": first_day,
            "day_after_last": last_day + datetime.timedelta(days=1),
        },
    )
    return [
        RestockWeek(
            week_start=week_row.week_start,
            added_units=week_row.added_units,
            removed_units=week_row.removed_units,
        )
        for week_row in week_rows
    ]


def _get_or_create_import_user(session: Session) -> int:
    existing_id = session.scalar(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": IMPORT_USER_EMAIL},
    )
    if existing_id is not None:
        return existing_id
    import_user = User(
        email=IMPORT_USER_EMAIL,
        full_name=IMPORT_USER_FULL_NAME,
        password_hash=UNUSABLE_PASSWORD_HASH,
        role=UserRole.ops_manager,
        is_active=False,
    )
    session.add(import_user)
    session.flush()
    return import_user.id


def _create_placeholder_fridges(
    session: Session,
    plan: ImportPlan,
    catalogue: Catalogue,
) -> list[str]:
    names_to_create = plan.placeholder_fridges_to_create(catalogue)
    for friendly_name in names_to_create:
        placeholder = Fridge(
            husky_id=PLACEHOLDER_FRIDGE_HUSKY_IDS[friendly_name],
            friendly_name=friendly_name,
            is_active=False,
            local_status=PLACEHOLDER_LOCAL_STATUS,
        )
        session.add(placeholder)
    session.flush()
    return names_to_create


def _write_dispatches(
    session: Session,
    plan: ImportPlan,
    import_user_id: int,
    fridge_id_by_name: dict[str, int],
    summary: WriteSummary,
) -> None:
    delivery_dates = [dispatch.delivery_date for dispatch in plan.dispatches]
    existing_by_date = _find_existing_dispatches(session, delivery_dates, import_user_id)
    dispatches_to_insert, replaced_ids = _split_by_existing(
        planned_items=plan.dispatches,
        key_of=_dispatch_key,
        existing_by_key=existing_by_date,
        kind="dispatch",
        summary=summary,
    )
    session.execute(text("DELETE FROM dispatches WHERE id = ANY(:ids)"), {"ids": replaced_ids})
    summary.dispatches_replaced = len(replaced_ids)
    if not dispatches_to_insert:
        return

    dispatch_rows = [_dispatch_row(dispatch, import_user_id) for dispatch in dispatches_to_insert]
    inserted = session.execute(
        insert(Dispatch).returning(Dispatch.id, Dispatch.delivery_date),
        dispatch_rows,
    )
    dispatch_id_by_date = {row.delivery_date: row.id for row in inserted}
    summary.dispatches_inserted = len(dispatch_id_by_date)
    print(f"  {summary.dispatches_inserted} dispatch batches inserted", flush=True)

    line_rows = []
    for dispatch in dispatches_to_insert:
        dispatch_id = dispatch_id_by_date[dispatch.delivery_date]
        for line in dispatch.lines:
            line_rows.append(
                {
                    "dispatch_id": dispatch_id,
                    "fridge_id": fridge_id_by_name[line.fridge_name],
                    "product_id": line.product_id,
                    "delivery_date": dispatch.delivery_date,
                    "qty": line.qty,
                    "unit_purchase_price": line.unit_purchase_price,
                    "unit_sales_price": line.unit_sales_price,
                    "vat_rate": line.vat_rate,
                }
            )
    summary.dispatch_lines_inserted = _insert_in_chunks(session, DispatchLine, line_rows)


def _write_orders(
    session: Session,
    plan: ImportPlan,
    import_user_id: int,
    summary: WriteSummary,
) -> None:
    order_numbers = [order.order_no for order in plan.orders]
    existing_by_order_no = _find_existing_orders(session, order_numbers, import_user_id)
    orders_to_insert, replaced_ids = _split_by_existing(
        planned_items=plan.orders,
        key_of=_order_key,
        existing_by_key=existing_by_order_no,
        kind="purchase order",
        summary=summary,
    )
    session.execute(
        text("DELETE FROM purchase_orders WHERE id = ANY(:ids)"),
        {"ids": replaced_ids},
    )
    summary.orders_replaced = len(replaced_ids)
    if not orders_to_insert:
        return

    order_rows = [_order_row(order, import_user_id) for order in orders_to_insert]
    inserted = session.execute(
        insert(PurchaseOrder).returning(PurchaseOrder.id, PurchaseOrder.order_no),
        order_rows,
    )
    order_id_by_number = {row.order_no: row.id for row in inserted}
    summary.orders_inserted = len(order_id_by_number)
    print(f"  {summary.orders_inserted} purchase orders inserted", flush=True)

    line_rows = []
    for order in orders_to_insert:
        order_id = order_id_by_number[order.order_no]
        for line in order.lines:
            line_rows.append(
                {
                    "po_id": order_id,
                    "product_id": line.product_id,
                    "qty_ordered": line.qty_ordered,
                    "qty_received": line.qty_received,
                    "unit_price": line.unit_price,
                    "vat_rate": line.vat_rate,
                }
            )
    summary.order_lines_inserted = _insert_in_chunks(session, PurchaseOrderLine, line_rows)


def _write_targets(
    session: Session,
    plan: ImportPlan,
    fridge_id_by_name: dict[str, int],
    summary: WriteSummary,
) -> None:
    existing_target_rows = session.execute(
        text("SELECT fridge_id, product_id FROM product_targets")
    )
    existing_keys = {(target.fridge_id, target.product_id) for target in existing_target_rows}
    target_rows = [
        {
            "fridge_id": fridge_id_by_name[target.fridge_name],
            "product_id": target.product_id,
            "target_qty": target.target_qty,
        }
        for target in plan.targets
    ]
    if not target_rows:
        return
    upsert = postgres_insert(ProductTarget).values(target_rows)
    upsert = upsert.on_conflict_do_update(
        index_elements=[ProductTarget.fridge_id, ProductTarget.product_id],
        set_={
            "target_qty": upsert.excluded.target_qty,
            "updated_at": text("now()"),
        },
    )
    session.execute(upsert)
    for target_row in target_rows:
        target_key = (target_row["fridge_id"], target_row["product_id"])
        if target_key in existing_keys:
            summary.targets_updated += 1
        else:
            summary.targets_inserted += 1


def _raise_order_counters(session: Session, plan: ImportPlan, summary: WriteSummary) -> None:
    """Move each year's counter past the highest workbook order number, never backwards."""
    summary.order_counters_before = _load_order_counters(session)
    highest_by_year = highest_order_sequence_by_year(plan.workbook_order_numbers)
    for year, highest_sequence in highest_by_year.items():
        session.execute(
            text(
                """
                INSERT INTO order_no_counters (year, last_seq)
                VALUES (:year, :last_seq)
                ON CONFLICT (year) DO UPDATE
                SET last_seq = GREATEST(order_no_counters.last_seq, EXCLUDED.last_seq)
                """
            ),
            {"year": year, "last_seq": highest_sequence},
        )
    summary.order_counters_after = _load_order_counters(session)


def _load_order_counters(session: Session) -> dict[int, int]:
    counter_rows = session.execute(text("SELECT year, last_seq FROM order_no_counters"))
    return {counter.year: counter.last_seq for counter in counter_rows}


def _split_by_existing[PlannedItem](
    planned_items: list[PlannedItem],
    key_of: Callable[[PlannedItem], str],
    existing_by_key: dict[str, ExistingRecord],
    kind: str,
    summary: WriteSummary,
) -> tuple[list[PlannedItem], list[int]]:
    """Planned items to insert, and ids of imported rows they replace; collisions skipped."""
    items_to_insert = []
    replaced_ids = []
    for planned_item in planned_items:
        existing = existing_by_key.get(key_of(planned_item))
        if existing is None:
            items_to_insert.append(planned_item)
            continue
        if classify_existing(existing) is ExistingAction.COLLISION:
            summary.collisions.append(Collision(kind=kind, record=existing))
            continue
        replaced_ids.append(existing.id)
        items_to_insert.append(planned_item)
    return items_to_insert, replaced_ids


def _find_existing_dispatches(
    session: Session,
    delivery_dates: list[datetime.date],
    import_user_id: int,
) -> dict[str, ExistingRecord]:
    rows = session.execute(
        text(
            """
            SELECT dispatch.id,
                   dispatch.delivery_date::text AS key,
                   dispatch.status,
                   dispatch.created_by IS NOT DISTINCT FROM :import_user_id AS is_imported,
                   (SELECT count(*) FROM dispatch_lines AS line
                     WHERE line.dispatch_id = dispatch.id) AS line_count,
                   (SELECT count(*) FROM stock_movements AS movement
                     JOIN dispatch_lines AS line ON line.id = movement.dispatch_line_id
                     WHERE line.dispatch_id = dispatch.id) AS stock_movement_count
            FROM dispatches AS dispatch
            WHERE dispatch.delivery_date = ANY(:delivery_dates)
            """
        ),
        {"delivery_dates": delivery_dates, "import_user_id": import_user_id},
    )
    return _records_by_key(rows)


def _find_existing_orders(
    session: Session,
    order_numbers: list[str],
    import_user_id: int,
) -> dict[str, ExistingRecord]:
    rows = session.execute(
        text(
            """
            SELECT purchase_order.id,
                   purchase_order.order_no AS key,
                   purchase_order.status,
                   purchase_order.created_by IS NOT DISTINCT FROM :import_user_id AS is_imported,
                   (SELECT count(*) FROM purchase_order_lines AS line
                     WHERE line.po_id = purchase_order.id) AS line_count,
                   (SELECT count(*) FROM stock_movements AS movement
                     JOIN purchase_order_lines AS line ON line.id = movement.po_line_id
                     WHERE line.po_id = purchase_order.id) AS stock_movement_count
            FROM purchase_orders AS purchase_order
            WHERE purchase_order.order_no = ANY(:order_numbers)
            """
        ),
        {"order_numbers": order_numbers, "import_user_id": import_user_id},
    )
    return _records_by_key(rows)


def _records_by_key(rows) -> dict[str, ExistingRecord]:
    records = {}
    for row in rows:
        records[row.key] = ExistingRecord(
            id=row.id,
            key=row.key,
            status=row.status,
            is_imported=row.is_imported,
            line_count=row.line_count,
            stock_movement_count=row.stock_movement_count,
        )
    return records


def _insert_in_chunks(session: Session, model: type, rows: list[dict]) -> int:
    for chunk_start in range(0, len(rows), LINE_INSERT_CHUNK_SIZE):
        chunk = rows[chunk_start : chunk_start + LINE_INSERT_CHUNK_SIZE]
        session.execute(insert(model), chunk)
        inserted_so_far = chunk_start + len(chunk)
        print(f"  {model.__tablename__}: {inserted_so_far}/{len(rows)} inserted", flush=True)
    return len(rows)


def _dispatch_row(dispatch: PlannedDispatch, import_user_id: int) -> dict:
    return {
        "delivery_date": dispatch.delivery_date,
        "iso_week": dispatch.delivery_date.isocalendar().week,
        "weekday": dispatch.delivery_date.isoweekday(),
        "status": dispatch.status,
        "confirmed_at": dispatch.confirmed_at,
        "created_by": import_user_id,
    }


def _order_row(order: PlannedOrder, import_user_id: int) -> dict:
    return {
        "order_no": order.order_no,
        "supplier_id": order.supplier_id,
        "status": order.status,
        "order_date": order.order_date,
        "expected_delivery_date": order.expected_delivery_date,
        "delivery_address": order.delivery_address,
        "comment": order.comment,
        "total_ex_vat": order.total_ex_vat,
        "total_vat": order.total_vat,
        "total_incl_vat": order.total_incl_vat,
        "created_by": import_user_id,
    }


def _dispatch_key(dispatch: PlannedDispatch) -> str:
    return dispatch.delivery_date.isoformat()


def _order_key(order: PlannedOrder) -> str:
    return order.order_no
