"""Weekly-menu workflow service (D2) - the (iso_year, week_no, day_name) stage
between forecast and dispatch.

The pipeline is import -> edit -> save -> load-saved with explicit
overwrite-confirm, mirroring the forecast and dispatch stages:

* :func:`import_from_forecast` COMPUTES (does not persist) a draft grid by
  splitting each fridge x category forecast quantity across that category's
  active products in proportion to product score (largest-remainder rounding),
  so the sum of per-product integer allocations equals the rounded forecast.
* :func:`save_menu` persists the edited grid keyed on (year, iso_week,
  day_name). A saved menu already existing for the key yields
  ``409 {code:"exists"}`` unless ``overwrite`` is set, in which case the prior
  ``menu_lines`` are deleted and the fresh grid reinserted in one transaction,
  with an audit row.
* :func:`get_saved_menu` loads a previously saved grid (import-from-database).
* :func:`aggregate_supplier_quantities` powers the per-supplier draft PO.

The fridge x product quantity grid lives in ``menu_lines`` (migration 0005),
which has no ORM model, so this service reads/writes it via SQL ``text()``.
``weekly_menus`` gains an explicit ``day_name`` (unset by the legacy ORM path,
so day-keyed rows are inserted via SQL here too).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.master import Category, Fridge, Product
from app.models.planning import ProductScore
from app.schemas.masters import api_error
from app.services import forecast_service
from app.services.stock_service import record_audit

MENU_STATUS_SAVED = "active"


@dataclass(frozen=True)
class MenuGridFridge:
    fridge_id: int
    friendly_name: str


@dataclass(frozen=True)
class MenuGridProduct:
    product_id: int
    product_name: str
    category_id: int


@dataclass(frozen=True)
class MenuGridCategory:
    category_id: int
    category_name: str
    product_ids: list[int]


@dataclass(frozen=True)
class MenuGridCell:
    fridge_id: int
    product_id: int
    qty: int


@dataclass(frozen=True)
class MenuGrid:
    menu_id: int | None
    year: int
    week: int
    day_name: str
    fridges: list[MenuGridFridge]
    products: list[MenuGridProduct]
    categories: list[MenuGridCategory]
    cells: list[MenuGridCell]


@dataclass(frozen=True)
class MenuLineInput:
    fridge_id: int
    product_id: int
    qty: int


@dataclass(frozen=True)
class MenuDraftLine:
    product_id: int
    code: str
    name: str
    qty: int
    unit_price: int  # cents
    vat_rate: Decimal


def _largest_remainder(target: int, weights: list[Decimal]) -> list[int]:
    """Distribute ``target`` integer units across ``weights`` proportionally.

    Largest-remainder method: floors sum to <= target, leftover units go to the
    highest fractional remainders (ties broken by weight), so the per-item
    integers sum back to exactly ``target``.
    """
    total = sum(weights, Decimal("0"))
    if target <= 0 or total <= 0:
        return [0] * len(weights)
    exact = [Decimal(target) * weight / total for weight in weights]
    floors = [int(value) for value in exact]
    leftover = target - sum(floors)
    order = sorted(
        range(len(weights)),
        key=lambda i: (exact[i] - floors[i], weights[i]),
        reverse=True,
    )
    for step in range(leftover):
        floors[order[step % len(order)]] += 1
    return floors


def _grid_from_cells(
    *,
    menu_id: int | None,
    year: int,
    week: int,
    day_name: str,
    raw_cells: list[tuple[int, int, int]],
    session: Session,
) -> MenuGrid:
    """Assemble a :class:`MenuGrid` from ``(fridge_id, product_id, qty)`` tuples."""
    fridge_ids = sorted({fridge_id for fridge_id, _pid, _qty in raw_cells})
    product_ids = sorted({product_id for _fid, product_id, _qty in raw_cells})

    fridges = [
        MenuGridFridge(fridge_id=fridge.id, friendly_name=fridge.friendly_name)
        for fridge in session.execute(
            select(Fridge).where(Fridge.id.in_(fridge_ids)).order_by(Fridge.friendly_name)
        )
        .scalars()
        .all()
    ]
    product_rows = list(
        session.execute(
            select(Product).where(Product.id.in_(product_ids)).order_by(Product.name)
        )
        .scalars()
        .all()
    )
    products = [
        MenuGridProduct(
            product_id=product.id,
            product_name=product.name,
            category_id=product.category_id,
        )
        for product in product_rows
    ]
    category_names = {
        category.id: category.name
        for category in session.execute(select(Category)).scalars().all()
    }
    products_by_category: dict[int, list[int]] = {}
    for product in product_rows:
        products_by_category.setdefault(product.category_id, []).append(product.id)
    categories = [
        MenuGridCategory(
            category_id=category_id,
            category_name=category_names.get(category_id, ""),
            product_ids=pids,
        )
        for category_id, pids in sorted(products_by_category.items())
    ]
    cells = [
        MenuGridCell(fridge_id=fridge_id, product_id=product_id, qty=qty)
        for fridge_id, product_id, qty in raw_cells
    ]
    return MenuGrid(
        menu_id=menu_id,
        year=year,
        week=week,
        day_name=day_name,
        fridges=fridges,
        products=products,
        categories=categories,
        cells=cells,
    )


def _category_products_by_score(
    session: Session,
) -> tuple[dict[int, list[int]], dict[int, Decimal]]:
    """Active products grouped by category with their latest final score.

    Products with no score fall back to weight 1 so a scoreless category still
    allocates evenly rather than dropping to zero.
    """
    products_by_category: dict[int, list[int]] = {}
    for product in session.execute(
        select(Product).where(Product.is_active.is_(True)).order_by(Product.name)
    ).scalars().all():
        products_by_category.setdefault(product.category_id, []).append(product.id)

    latest_period = session.execute(
        select(ProductScore.period_end).order_by(ProductScore.period_end.desc()).limit(1)
    ).scalar()
    scores: dict[int, Decimal] = {}
    if latest_period is not None:
        for product_id, final_score in session.execute(
            select(ProductScore.product_id, ProductScore.final_score).where(
                ProductScore.period_end == latest_period
            )
        ).all():
            scores[product_id] = final_score
    return products_by_category, scores


def import_from_forecast(
    *,
    year: int,
    week: int,
    day_name: str,
    delivery_date,
    category_id: int | None = None,
    session: Session,
) -> MenuGrid:
    """Seed a draft menu grid (NOT persisted) from the saved forecast (D2).

    Each fridge x category forecast quantity is split across that category's
    active products in proportion to product score. When ``category_id`` is set,
    only that category is computed (the Excel "pull one category" flow); the
    caller merges the result into the existing grid.
    """
    run = forecast_service.get_saved_run(delivery_date, session)
    if run is None:
        raise api_error(
            404,
            "not_found",
            "No saved forecast to import from for this key",
            {"year": year, "week": week, "day_name": day_name},
        )
    results = forecast_service.get_results(run.id, session)
    products_by_category, scores = _category_products_by_score(session)

    raw_cells: list[tuple[int, int, int]] = []
    for result in results:
        if category_id is not None and result.category_id != category_id:
            continue
        product_ids = products_by_category.get(result.category_id, [])
        if not product_ids:
            continue
        target = int(result.forecast_qty.to_integral_value(rounding="ROUND_HALF_UP"))
        if target <= 0:
            continue
        weights = [scores.get(pid, Decimal("0")) for pid in product_ids]
        if sum(weights, Decimal("0")) <= 0:
            weights = [Decimal("1")] * len(product_ids)
        allocations = _largest_remainder(target, weights)
        for product_id, qty in zip(product_ids, allocations):
            if qty > 0:
                raw_cells.append((result.fridge_id, product_id, qty))

    return _grid_from_cells(
        menu_id=None,
        year=year,
        week=week,
        day_name=day_name,
        raw_cells=raw_cells,
        session=session,
    )


def _find_menu_id(year: int, week: int, day_name: str, session: Session) -> int | None:
    return session.execute(
        text(
            "SELECT id FROM weekly_menus "
            "WHERE year = :y AND iso_week = :w AND day_name = :d"
        ),
        {"y": year, "w": week, "d": day_name},
    ).scalar()


def _category_has_lines(menu_id: int, category_id: int, session: Session) -> bool:
    """True when the saved menu already holds lines for this category."""
    return bool(
        session.execute(
            text(
                "SELECT 1 FROM menu_lines "
                "WHERE menu_id = :id AND category_id = :cat LIMIT 1"
            ),
            {"id": menu_id, "cat": category_id},
        ).scalar()
    )


def save_menu(
    *,
    year: int,
    week: int,
    day_name: str,
    lines: list[MenuLineInput],
    overwrite: bool,
    category_id: int | None = None,
    user_id: int | None,
    session: Session,
) -> MenuGrid:
    """Persist the menu grid for the key with overwrite-confirm semantics (D2).

    When ``category_id`` is set, only that category's lines are replaced (the
    Excel "save one category" flow): other categories' saved lines are left
    intact, and the ``exists`` conflict fires only if THAT category already has
    saved lines. When ``category_id`` is None the whole menu is replaced.
    """
    scoped = category_id is not None
    existing_id = _find_menu_id(year, week, day_name, session)
    if existing_id is not None and not overwrite:
        conflict = (
            _category_has_lines(int(existing_id), category_id, session)
            if scoped
            else True
        )
        if conflict:
            raise api_error(
                409,
                "exists",
                "A saved menu already exists for this key; resend with overwrite=true",
                {
                    "year": year,
                    "week": week,
                    "day_name": day_name,
                    "menu_id": int(existing_id),
                    "category_id": category_id,
                },
            )

    positive = [line for line in lines if line.qty > 0]
    product_ids = {line.product_id for line in positive}
    category_of = {
        product.id: product.category_id
        for product in session.execute(
            select(Product).where(Product.id.in_(product_ids))
        )
        .scalars()
        .all()
    }
    missing = product_ids - set(category_of)
    if missing:
        raise api_error(
            422,
            "validation_error",
            "Unknown product in menu lines",
            {"product_ids": sorted(missing)},
        )
    if scoped:
        outside = sorted(
            pid for pid in product_ids if category_of[pid] != category_id
        )
        if outside:
            raise api_error(
                422,
                "validation_error",
                "Menu lines contain products outside the target category",
                {"category_id": category_id, "product_ids": outside},
            )

    if existing_id is None:
        menu_id = int(
            session.execute(
                text(
                    "INSERT INTO weekly_menus (year, iso_week, day_name, status) "
                    "VALUES (:y, :w, :d, :status) RETURNING id"
                ),
                {"y": year, "w": week, "d": day_name, "status": MENU_STATUS_SAVED},
            ).scalar_one()
        )
    else:
        menu_id = int(existing_id)
        if scoped:
            session.execute(
                text(
                    "DELETE FROM menu_lines WHERE menu_id = :id AND category_id = :cat"
                ),
                {"id": menu_id, "cat": category_id},
            )
        else:
            session.execute(
                text("DELETE FROM menu_lines WHERE menu_id = :id"), {"id": menu_id}
            )
        session.execute(
            text(
                "UPDATE weekly_menus SET status = :status, updated_at = now() "
                "WHERE id = :id"
            ),
            {"status": MENU_STATUS_SAVED, "id": menu_id},
        )

    for line in positive:
        session.execute(
            text(
                "INSERT INTO menu_lines (menu_id, fridge_id, product_id, category_id, qty) "
                "VALUES (:menu_id, :fridge_id, :product_id, :category_id, :qty)"
            ),
            {
                "menu_id": menu_id,
                "fridge_id": line.fridge_id,
                "product_id": line.product_id,
                "category_id": category_of[line.product_id],
                "qty": line.qty,
            },
        )

    if scoped:
        action = "menu.save.category"
    elif existing_id is not None:
        action = "menu.save.overwrite"
    else:
        action = "menu.save"
    record_audit(
        session,
        action=action,
        entity="weekly_menus",
        entity_id=menu_id,
        before={"menu_id": int(existing_id)} if existing_id is not None else None,
        after={
            "year": year,
            "week": week,
            "day_name": day_name,
            "category_id": category_id,
            "lines": len(positive),
        },
        user_id=user_id,
    )
    session.commit()
    return _load_grid(menu_id, year, week, day_name, session)


def _load_grid(
    menu_id: int, year: int, week: int, day_name: str, session: Session
) -> MenuGrid:
    rows = session.execute(
        text(
            "SELECT fridge_id, product_id, qty FROM menu_lines WHERE menu_id = :id"
        ),
        {"id": menu_id},
    ).all()
    raw_cells = [(row.fridge_id, row.product_id, int(row.qty)) for row in rows]
    return _grid_from_cells(
        menu_id=menu_id,
        year=year,
        week=week,
        day_name=day_name,
        raw_cells=raw_cells,
        session=session,
    )


def get_saved_menu(
    *, year: int, week: int, day_name: str, session: Session
) -> MenuGrid | None:
    """Load a previously saved menu grid for the key, or None (D2)."""
    menu_id = _find_menu_id(year, week, day_name, session)
    if menu_id is None:
        return None
    return _load_grid(int(menu_id), year, week, day_name, session)


def aggregate_supplier_quantities(
    *, year: int, week: int, day_name: str, supplier_id: int, session: Session
) -> dict[int, int]:
    """Sum saved-menu quantities per product for one supplier (draft-PO source).

    Raises 404 when no saved menu exists for the key.
    """
    menu_id = _find_menu_id(year, week, day_name, session)
    if menu_id is None:
        raise api_error(
            404,
            "not_found",
            "No saved menu for this key",
            {"year": year, "week": week, "day_name": day_name},
        )
    rows = session.execute(
        text(
            "SELECT ml.product_id AS product_id, SUM(ml.qty) AS qty "
            "FROM menu_lines ml JOIN products p ON p.id = ml.product_id "
            "WHERE ml.menu_id = :menu_id AND p.supplier_id = :supplier_id "
            "GROUP BY ml.product_id"
        ),
        {"menu_id": int(menu_id), "supplier_id": supplier_id},
    ).all()
    return {row.product_id: int(row.qty) for row in rows if int(row.qty) > 0}


def preview_supplier_po_lines(
    *,
    year: int,
    week: int,
    day_name: str,
    supplier_id: int,
    session: Session,
) -> list[MenuDraftLine]:
    """Draft PO lines for one supplier from a saved menu WITHOUT persisting.

    Reuses aggregate_supplier_quantities (per-product qty for the supplier),
    then prices each line from the product catalogue. Read-only preview: the
    caller reviews/edits before creating the PO. Returns [] when the supplier
    has no menu quantities. A missing saved menu still raises 404 via the
    aggregation call.
    """
    quantities = aggregate_supplier_quantities(
        year=year, week=week, day_name=day_name, supplier_id=supplier_id, session=session
    )
    if not quantities:
        return []
    products = (
        session.execute(select(Product).where(Product.id.in_(quantities.keys())))
        .scalars()
        .all()
    )
    by_id = {product.id: product for product in products}
    lines = [
        MenuDraftLine(
            product_id=product_id,
            code=by_id[product_id].code,
            name=by_id[product_id].name,
            qty=qty,
            unit_price=by_id[product_id].purchase_price,
            vat_rate=by_id[product_id].vat_rate,
        )
        for product_id, qty in quantities.items()
        if product_id in by_id
    ]
    lines.sort(key=lambda line: line.name.lower())
    return lines
