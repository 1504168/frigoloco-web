"""Weekly-menu workflow service (D2) - the (iso_year, week_no, day_name) stage
between forecast and dispatch.

The pipeline is import -> edit -> save -> load-saved with explicit
overwrite-confirm, mirroring the forecast and dispatch stages:

* :func:`import_from_forecast` COMPUTES (does not persist) a draft grid by
  splitting each fridge x category forecast quantity over the week menu's
  products of that category (spec 0008): by rating, optionally sold-first, and
  optionally cut by the good units each product still has in the fridge (spec 0009)
  and scaled by the sales speed per fridge x category (spec 0010).
* :func:`save_menu` persists the edited grid keyed on (year, iso_week,
  day_name) and makes its products the week menu. A saved menu already
  existing for the key yields ``409 {code:"exists"}`` unless ``overwrite`` is
  set, in which case the prior ``menu_lines`` are deleted and the fresh grid
  reinserted in one transaction, with an audit row.
* :func:`get_saved_menu` loads a previously saved grid (import-from-database).
* :func:`aggregate_supplier_quantities` powers the per-supplier draft PO.

The week menu is the ``weekly_menus`` row with ``day_name = ''`` and its product
list is ``menu_products``: every day of the ISO week shows the same products.

The fridge x product quantity grid lives in ``menu_lines`` (migration 0005),
which has no ORM model, so this service reads/writes it via SQL ``text()``.
``weekly_menus`` gains an explicit ``day_name`` (unset by the legacy ORM path,
so day-keyed rows are inserted via SQL here too).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

from app.husky.sync import effective_status_clause
from app.models.master import Category, Fridge, FridgeDeliveryConfig, Product, ProductTarget
from app.models.planning import ForecastResult, MenuLine, MenuProduct, WeeklyMenu
from app.schemas.masters import ApiException, api_error
from app.services import (
    client_rules_service,
    forecast_service,
    fridge_stock_service,
    replenishment_service,
    sales_pace_service,
    scoring_service,
    stock_fit_service,
)
from app.services.menu_allocation_service import (
    FridgeStockReadings,
    RatingWeights,
    is_target_replenish_category,
    load_fridge_stock_readings,
    rating_weights,
)
from app.services.replenishment_service import split_by_weight, split_category_quantity
from app.services.stock_service import record_audit, resolve_delivery_date

MENU_STATUS_SAVED = "active"
ACTIVE_STATUS = "active"
WEEK_MENU_DAY_NAME = ""
# A rating suggestion starts from the best-rated products of a category, not all of them.
SUGGESTED_PRODUCTS_PER_CATEGORY = 6
UNSCORED_RANK = Decimal("-1")
NO_SHELF_LIFE_CHECK = sales_pace_service.ShelfLifeCheck(
    shelf_life_days_by_product={},
    coverage_days_by_fridge={},
)


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
class WeekMenu:
    """The products chosen for an ISO week, per category (``menu_id`` None when unsaved)."""

    menu_id: int | None
    year: int
    week: int
    categories: list[MenuGridCategory]


@dataclass(frozen=True)
class MenuStockCut:
    """Why an imported cell is lower: the product's good units already in the fridge."""

    fridge_id: int
    product_id: int
    in_fridge_units: int
    reduced_by: int


@dataclass(frozen=True)
class ImportFridgeStock:
    """Good in-fridge units per (fridge, product) for one import, plus the stale fridges."""

    good_units_by_key: dict[tuple[int, int], int]
    stale_fridge_ids: list[int]

    def good_units(self, fridge_id: int, product_id: int) -> int:
        return self.good_units_by_key.get((fridge_id, product_id), 0)


NO_FRIDGE_STOCK = ImportFridgeStock(good_units_by_key={}, stale_fridge_ids=[])


@dataclass(frozen=True)
class SnackDrinkTargets:
    """Per-fridge targets of Snacks and Drinks plus the live in-fridge units they refill from."""

    target_qty_by_key: dict[tuple[int, int], int]
    readings: FridgeStockReadings

    def fridge_has_targets(self, fridge_id: int, product_ids: list[int]) -> bool:
        return any((fridge_id, product_id) in self.target_qty_by_key for product_id in product_ids)

    def restock_qty(self, fridge_id: int, product_id: int) -> int:
        target_qty = self.target_qty_by_key.get((fridge_id, product_id), 0)
        return max(target_qty - self.readings.units(fridge_id, product_id), 0)


NO_SNACK_DRINK_TARGETS = SnackDrinkTargets(
    target_qty_by_key={},
    readings=FridgeStockReadings(),
)


@dataclass(frozen=True)
class TargetProduct:
    product_id: int
    product_code: str
    product_name: str


@dataclass(frozen=True)
class TargetCategory:
    category_id: int
    category_name: str
    products: list[TargetProduct]


@dataclass(frozen=True)
class MenuCellsStockFit:
    cells: list[MenuGridCell]
    cuts: list[stock_fit_service.ProductStockCut]


@dataclass(frozen=True)
class MenuImport:
    grid: MenuGrid
    # True when nothing was chosen for the imported scope, so products came from ratings.
    used_rating_suggestion: bool
    categories_without_products: list[int]
    sold_first: bool
    # False when the switch was off or the delivery is not the next one (stock says nothing).
    fridge_stock_applied: bool
    stale_stock_fridge_ids: list[int]
    stock_cuts: list[MenuStockCut]
    sales_speed_adjustments: list[sales_pace_service.SalesSpeedAdjustment]
    # Products a sales-speed raise skipped because they would expire before the coverage end.
    shelf_life_holds: list[sales_pace_service.ShelfLifeHold]
    # Products that got units with their category's mean score because they have no score yet.
    default_score_product_ids: list[int]
    # Products cut down to the warehouse stock when "fit to stock" was asked.
    warehouse_stock_cuts: list[stock_fit_service.ProductStockCut]
    # Fridges whose Snacks and Drinks were refilled to their targets, not split.
    target_refill_fridge_ids: list[int]
    # Imported (fridge, product) cells whose client excludes one of the product's tags.
    rule_violations: list[client_rules_service.RuleViolation]


@dataclass(frozen=True)
class CategorySplit:
    """One fridge x category: its products, their rating weights and units sold since delivery."""

    product_ids: list[int]
    weights: RatingWeights
    sold_quantities: list[int]

    def split(self, target: int) -> list[int]:
        """Sold-first split in which a product without a score keeps its plain rating share.

        A new product sold nothing since the last delivery (it was not in the fridge yet),
        so sold-first alone would leave it only what the sold products did not take.
        """
        default_score_ids = set(self.weights.default_score_product_ids)
        has_sales = any(sold_qty > 0 for sold_qty in self.sold_quantities)
        if not default_score_ids or not has_sales:
            return split_category_quantity(
                target=target,
                weights=self.weights.weights,
                sold_quantities=self.sold_quantities,
            )
        rating_shares = split_by_weight(target, self.weights.weights)
        scored_positions = [
            position
            for position, product_id in enumerate(self.product_ids)
            if product_id not in default_score_ids
        ]
        scored_rating_units = sum(rating_shares[position] for position in scored_positions)
        scored_shares = split_category_quantity(
            target=scored_rating_units,
            weights=[self.weights.weights[position] for position in scored_positions],
            sold_quantities=[self.sold_quantities[position] for position in scored_positions],
        )
        shares = list(rating_shares)
        for position, scored_share in zip(scored_positions, scored_shares):
            shares[position] = scored_share
        return shares

    def default_score_ids_with_units(self, shares: list[int]) -> list[int]:
        default_score_ids = set(self.weights.default_score_product_ids)
        return [
            product_id
            for product_id, share in zip(self.product_ids, shares)
            if share > 0 and product_id in default_score_ids
        ]


@dataclass(frozen=True)
class MenuLineInput:
    fridge_id: int
    product_id: int
    qty: int


@dataclass(frozen=True)
class MenuStockBalance:
    product_id: int
    in_stock_qty: int
    on_order_qty: int


@dataclass(frozen=True)
class MenuDraftLine:
    product_id: int
    code: str
    name: str
    qty: int
    unit_price: int  # cents
    vat_rate: Decimal


def _grid_from_cells(
    *,
    menu_id: int | None,
    year: int,
    week: int,
    day_name: str,
    cells: list[MenuGridCell],
    menu_product_ids: set[int],
    session: Session,
) -> MenuGrid:
    """Assemble a :class:`MenuGrid`: the menu's products plus any product with a cell."""
    fridges = list_delivery_day_fridges(
        delivery_date=resolve_delivery_date(year, week, day_name),
        fridge_ids_with_lines={cell.fridge_id for cell in cells},
        session=session,
    )
    cell_product_ids = {cell.product_id for cell in cells}
    product_rows = _products_by_name(cell_product_ids | menu_product_ids, session)
    products = [
        MenuGridProduct(
            product_id=product.id,
            product_name=product.name,
            category_id=product.category_id,
        )
        for product in product_rows
    ]
    return MenuGrid(
        menu_id=menu_id,
        year=year,
        week=week,
        day_name=day_name,
        fridges=fridges,
        products=products,
        categories=_categories_in_display_order(product_rows, session),
        cells=cells,
    )


def list_delivery_day_fridges(
    *,
    delivery_date: datetime.date,
    fridge_ids_with_lines: set[int],
    session: Session,
) -> list[MenuGridFridge]:
    """Grid fridge rows for a delivery day, ordered by name.

    Every active fridge delivered on the date's weekday gets a row, so a plan can be
    built from scratch, plus any fridge that already has lines (kept even if its
    delivery config changed since).
    """
    delivery_fridge_ids = _delivery_fridge_ids(delivery_date.isoweekday(), session)
    fridge_ids = fridge_ids_with_lines | delivery_fridge_ids
    fridge_rows = session.execute(
        select(Fridge).where(Fridge.id.in_(fridge_ids)).order_by(Fridge.friendly_name)
    ).scalars()
    return [
        MenuGridFridge(fridge_id=fridge.id, friendly_name=fridge.friendly_name)
        for fridge in fridge_rows
    ]


def _delivery_fridge_ids(delivery_weekday: int, session: Session) -> set[int]:
    """Active fridges with a delivery configured on this ISO weekday."""
    fridge_ids = session.execute(
        select(Fridge.id)
        .join(FridgeDeliveryConfig, FridgeDeliveryConfig.fridge_id == Fridge.id)
        .where(
            FridgeDeliveryConfig.weekday == delivery_weekday,
            effective_status_clause(Fridge, ACTIVE_STATUS),
        )
    ).scalars()
    return set(fridge_ids)


def _categories_in_display_order(
    product_rows: list[Product],
    session: Session,
) -> list[MenuGridCategory]:
    products_by_category: dict[int, list[int]] = {}
    for product in product_rows:
        products_by_category.setdefault(product.category_id, []).append(product.id)
    ordered_categories = session.execute(
        select(Category)
        .where(Category.id.in_(products_by_category))
        .order_by(Category.display_order, Category.name)
    ).scalars()
    return [
        MenuGridCategory(
            category_id=category.id,
            category_name=category.name,
            product_ids=products_by_category[category.id],
        )
        for category in ordered_categories
    ]


def _active_products_by_category(session: Session) -> dict[int, list[int]]:
    """Every active product id grouped by category, in name order."""
    active_products = session.execute(
        select(Product)
        .where(effective_status_clause(Product, ACTIVE_STATUS))
        .order_by(Product.name)
    ).scalars()
    return _group_by_category(list(active_products))


def _suggested_products_by_category(
    scores: dict[int, Decimal],
    session: Session,
) -> dict[int, list[int]]:
    """The best-rated active products of each category, in name order."""

    def score_rank(product_id: int) -> Decimal:
        return scores.get(product_id, UNSCORED_RANK)

    active_products_by_category = _active_products_by_category(session)
    suggested_by_category: dict[int, list[int]] = {}
    for category_id, product_ids in active_products_by_category.items():
        ranked_product_ids = sorted(product_ids, key=score_rank, reverse=True)
        best_rated = set(ranked_product_ids[:SUGGESTED_PRODUCTS_PER_CATEGORY])
        suggested_by_category[category_id] = [
            product_id for product_id in product_ids if product_id in best_rated
        ]
    return suggested_by_category


def _split_at_sales_speed(
    *,
    fridge_id: int,
    category_target: int,
    adjusted_target: int,
    unraised_shares: list[int],
    category_split: CategorySplit,
    shelf_life_check: sales_pace_service.ShelfLifeCheck,
) -> sales_pace_service.ShelfLifeLimitedShares:
    """The split of the speed-adjusted target; a raise skips products that would expire."""
    adjusted_shares = category_split.split(adjusted_target)
    if adjusted_target <= category_target:
        return sales_pace_service.ShelfLifeLimitedShares(shares=adjusted_shares, holds=[])
    return sales_pace_service.keep_raise_within_shelf_life(
        fridge_id=fridge_id,
        product_ids=category_split.product_ids,
        raised_shares=adjusted_shares,
        unraised_shares=unraised_shares,
        shelf_life_check=shelf_life_check,
    )


def import_from_forecast(
    *,
    year: int,
    week: int,
    day_name: str,
    delivery_date: datetime.date,
    category_id: int | None = None,
    chosen_product_ids: list[int] | None = None,
    sold_first: bool = False,
    use_fridge_stock: bool = False,
    sales_speed: bool = False,
    fit_to_stock: bool = False,
    session: Session,
) -> MenuImport:
    """Seed a draft menu grid (NOT persisted) from the saved forecast (specs 0008, 0009).

    Each fridge x category forecast quantity is split over the chosen products of
    that category: ``chosen_product_ids`` (the products on screen) or else the saved
    week menu. With nothing chosen in scope, products are suggested from ratings.
    ``sold_first`` refills products sold since the last delivery first (not for
    Snacks and Drinks). ``use_fridge_stock`` gives each product only what its share
    needs beyond its good units in the fridge, for the next delivery only.
    ``sales_speed`` scales a fridge x category quantity by how fast it sells against its
    previous forecast (spec 0010). A fridge with Snacks and Drinks targets is refilled
    to them (``target - live units``) instead of the forecast split. ``fit_to_stock``
    cuts the result to the physical warehouse stock. When ``category_id`` is set
    only that category is computed; the caller merges the result into the existing grid.
    """
    run = forecast_service.get_saved_run(delivery_date, session)
    if run is None:
        raise api_error(
            404,
            "not_found",
            "No saved forecast to import from for this key",
            {"year": year, "week": week, "day_name": day_name},
        )
    all_results = forecast_service.get_results(run.id, session)
    results = [
        result
        for result in all_results
        if category_id is None or result.category_id == category_id
    ]

    if chosen_product_ids is None:
        chosen_ids = _week_product_ids(year, week, session)
    else:
        chosen_ids = set(chosen_product_ids)
    chosen_products = _products_by_name(chosen_ids, session)
    products_by_category = _keep_scope(_group_by_category(chosen_products), category_id)
    scores = scoring_service.load_latest_final_scores(session)
    used_rating_suggestion = not products_by_category
    if used_rating_suggestion:
        products_by_category = _keep_scope(
            _suggested_products_by_category(scores, session),
            category_id,
        )

    sold_by_fridge: dict[int, dict[int, int]] = {}
    if sold_first:
        sold_by_fridge = _sales_since_last_delivery(
            results=results,
            products_by_category=products_by_category,
            delivery_date=delivery_date,
            session=session,
        )
    fridge_stock_applied = use_fridge_stock and forecast_service.is_next_delivery(delivery_date)
    fridge_stock = NO_FRIDGE_STOCK
    if fridge_stock_applied:
        fridge_stock = _load_import_fridge_stock(results, delivery_date, session)
    # The saved forecast is already net of the category's good stock: the menu products'
    # part is added back so the per-product cut takes it off exactly once.
    residual_was_deducted = bool(run.params.get("residual_deduction", False))
    result_fridge_ids = sorted({result.fridge_id for result in results})
    speed_by_fridge_category: dict[tuple[int, int], sales_pace_service.SalesSpeedAdjustment] = {}
    shelf_life_check = NO_SHELF_LIFE_CHECK
    if sales_speed:
        speed_by_fridge_category = sales_pace_service.load_sales_speed_adjustments(
            fridge_ids=result_fridge_ids,
            category_ids=sorted(products_by_category),
            delivery_date=delivery_date,
            session=session,
        )
        shelf_life_check = sales_pace_service.load_shelf_life_check(
            fridge_ids=result_fridge_ids,
            product_ids=sorted(_flatten_product_ids(products_by_category)),
            delivery_date=delivery_date,
            session=session,
        )
    snack_drink_category_ids = _snack_drink_category_ids(products_by_category, session)
    snack_drink_targets = NO_SNACK_DRINK_TARGETS
    if snack_drink_category_ids:
        snack_drink_targets = _load_snack_drink_targets(results, session)
    cells: list[MenuGridCell] = []
    stock_cuts: list[MenuStockCut] = []
    sales_speed_adjustments: list[sales_pace_service.SalesSpeedAdjustment] = []
    shelf_life_holds: list[sales_pace_service.ShelfLifeHold] = []
    default_score_product_ids: set[int] = set()
    target_refill_fridge_ids: set[int] = set()
    for result in results:
        product_ids = products_by_category.get(result.category_id, [])
        if not product_ids:
            continue
        is_target_refill = (
            result.category_id in snack_drink_category_ids
            and snack_drink_targets.fridge_has_targets(result.fridge_id, product_ids)
        )
        if is_target_refill:
            cells.extend(_target_refill_cells(result.fridge_id, product_ids, snack_drink_targets))
            target_refill_fridge_ids.add(result.fridge_id)
            continue
        sold_by_product = sold_by_fridge.get(result.fridge_id, {})
        good_units = [
            fridge_stock.good_units(result.fridge_id, product_id) for product_id in product_ids
        ]
        category_target = _rounded_forecast(result)
        if residual_was_deducted:
            category_target += _residual_add_back(result, sum(good_units))
        category_split = CategorySplit(
            product_ids=product_ids,
            weights=rating_weights(product_ids, scores),
            sold_quantities=[sold_by_product.get(product_id, 0) for product_id in product_ids],
        )
        # Sales speed changes the demand, so it applies before the stock is taken off.
        speed = speed_by_fridge_category.get((result.fridge_id, result.category_id))
        shares = category_split.split(category_target)
        if speed is not None:
            sales_speed_adjustments.append(speed)
            speed_shares = _split_at_sales_speed(
                fridge_id=result.fridge_id,
                category_target=category_target,
                adjusted_target=_speed_adjusted_target(result, category_target, speed.factor),
                unraised_shares=shares,
                category_split=category_split,
                shelf_life_check=shelf_life_check,
            )
            shares = speed_shares.shares
            shelf_life_holds.extend(speed_shares.holds)
        default_score_product_ids.update(category_split.default_score_ids_with_units(shares))
        cut_quantities = replenishment_service.cut_by_fridge_stock(
            shares=shares,
            good_units=good_units,
        )
        for product_id, cut in zip(product_ids, cut_quantities):
            if cut.qty > 0:
                cells.append(
                    MenuGridCell(fridge_id=result.fridge_id, product_id=product_id, qty=cut.qty)
                )
            if cut.in_fridge_units > 0:
                stock_cuts.append(
                    MenuStockCut(
                        fridge_id=result.fridge_id,
                        product_id=product_id,
                        in_fridge_units=cut.in_fridge_units,
                        reduced_by=cut.reduced_by,
                    )
                )

    warehouse_stock_cuts: list[stock_fit_service.ProductStockCut] = []
    if fit_to_stock:
        stock_fit = _fit_cells_to_warehouse_stock(cells, session)
        cells = stock_fit.cells
        warehouse_stock_cuts = stock_fit.cuts

    # A suggestion shows only the products it filled, not every active product.
    menu_product_ids: set[int] = set()
    if not used_rating_suggestion:
        menu_product_ids = _flatten_product_ids(products_by_category)
    forecast_category_ids = {result.category_id for result in results}
    grid = _grid_from_cells(
        menu_id=None,
        year=year,
        week=week,
        day_name=day_name,
        cells=cells,
        menu_product_ids=menu_product_ids,
        session=session,
    )
    allocated_pairs = {(cell.fridge_id, cell.product_id) for cell in grid.cells if cell.qty > 0}
    rule_violations = client_rules_service.find_allocated_rule_violations(
        session,
        allocated_pairs,
        delivery_date,
    )
    return MenuImport(
        grid=grid,
        used_rating_suggestion=used_rating_suggestion,
        categories_without_products=sorted(forecast_category_ids - products_by_category.keys()),
        sold_first=sold_first,
        fridge_stock_applied=fridge_stock_applied,
        stale_stock_fridge_ids=_stale_fridge_ids(
            fridge_stock,
            snack_drink_targets,
            sorted(target_refill_fridge_ids),
        ),
        stock_cuts=stock_cuts,
        sales_speed_adjustments=sales_speed_adjustments,
        shelf_life_holds=shelf_life_holds,
        default_score_product_ids=sorted(default_score_product_ids),
        warehouse_stock_cuts=warehouse_stock_cuts,
        target_refill_fridge_ids=sorted(target_refill_fridge_ids),
        rule_violations=rule_violations,
    )


def get_week_menu(*, year: int, week: int, session: Session) -> WeekMenu:
    """The saved product list of an ISO week (empty when none is saved)."""
    product_rows = _products_by_name(_week_product_ids(year, week, session), session)
    return WeekMenu(
        menu_id=_find_menu_id(year, week, WEEK_MENU_DAY_NAME, session),
        year=year,
        week=week,
        categories=_categories_in_display_order(product_rows, session),
    )


def _week_product_ids(year: int, week: int, session: Session) -> set[int]:
    product_ids = session.execute(
        select(MenuProduct.product_id)
        .join(WeeklyMenu, WeeklyMenu.id == MenuProduct.menu_id)
        .where(
            WeeklyMenu.year == year,
            WeeklyMenu.iso_week == week,
            WeeklyMenu.day_name == WEEK_MENU_DAY_NAME,
        )
    ).scalars()
    return set(product_ids)


def _products_by_name(product_ids: set[int], session: Session) -> list[Product]:
    return list(
        session.execute(
            select(Product).where(Product.id.in_(product_ids)).order_by(Product.name)
        ).scalars()
    )


def _group_by_category(product_rows: list[Product]) -> dict[int, list[int]]:
    products_by_category: dict[int, list[int]] = {}
    for product in product_rows:
        products_by_category.setdefault(product.category_id, []).append(product.id)
    return products_by_category


def _keep_scope(
    products_by_category: dict[int, list[int]],
    category_id: int | None,
) -> dict[int, list[int]]:
    """Only the scoped category's entry when ``category_id`` is set."""
    if category_id is None:
        return products_by_category
    if category_id not in products_by_category:
        return {}
    return {category_id: products_by_category[category_id]}


def _flatten_product_ids(products_by_category: dict[int, list[int]]) -> set[int]:
    product_ids: set[int] = set()
    for category_product_ids in products_by_category.values():
        product_ids.update(category_product_ids)
    return product_ids


def _rounded_forecast(result: ForecastResult) -> int:
    return int(result.forecast_qty.to_integral_value(rounding="ROUND_HALF_UP"))


def _speed_adjusted_target(result: ForecastResult, category_target: int, factor: Decimal) -> int:
    """The target with the speed factor applied to the demand only, never to fridge stock.

    The demand is the gross forecast (before the fridge stock was deducted) when stored.
    """
    if result.gross_qty is None:
        demand_units = _rounded_forecast(result)
    else:
        demand_units = int(result.gross_qty.to_integral_value(rounding="ROUND_HALF_UP"))
    adjusted_demand_units = sales_pace_service.apply_sales_speed_factor(demand_units, factor)
    return max(category_target + adjusted_demand_units - demand_units, 0)


def _residual_add_back(result: ForecastResult, menu_good_units: int) -> int:
    """Good units to add back: never more than the forecast actually deducted.

    A forecast clamped at zero (residual above gross) deducted only its gross quantity.
    Runs saved before gross/residual were stored keep the plain add-back.
    """
    if result.gross_qty is None or result.residual_units is None:
        return menu_good_units
    gross_units = int(result.gross_qty.to_integral_value(rounding="ROUND_HALF_UP"))
    deducted_units = min(result.residual_units, gross_units)
    return min(menu_good_units, deducted_units)


def _sales_since_last_delivery(
    *,
    results: list[ForecastResult],
    products_by_category: dict[int, list[int]],
    delivery_date: datetime.date,
    session: Session,
) -> dict[int, dict[int, int]]:
    """Sold-first input: fridge -> product -> units sold since the last delivery.

    Snacks and Drinks keep their own replenishment, so they are left out.
    """
    category_rows = session.execute(
        select(Category).where(Category.id.in_(products_by_category))
    ).scalars()
    sold_first_products: dict[int, list[int]] = {}
    for category in category_rows:
        if not is_target_replenish_category(category.name):
            sold_first_products[category.id] = products_by_category[category.id]
    if not sold_first_products:
        return {}
    fridge_ids = {result.fridge_id for result in results}
    return replenishment_service.load_sales_since_last_delivery(
        fridge_ids=sorted(fridge_ids),
        category_ids=sorted(sold_first_products),
        product_ids=sorted(_flatten_product_ids(sold_first_products)),
        delivery_date=delivery_date,
        session=session,
    )


def _load_import_fridge_stock(
    results: list[ForecastResult],
    delivery_date: datetime.date,
    session: Session,
) -> ImportFridgeStock:
    """Good units per (fridge, product) read fresh now, flagging fridges with an old reading.

    A stale fridge still uses its last-known units, as the allocation route does.
    """
    forecast_fridge_ids = sorted({result.fridge_id for result in results})
    coverage_end_by_fridge = fridge_stock_service.load_coverage_ends(
        delivery_date=delivery_date,
        fridge_ids=forecast_fridge_ids,
        session=session,
    )
    good_stock = fridge_stock_service.load_good_stock_units(
        coverage_end_by_fridge=coverage_end_by_fridge,
        session=session,
    )
    good_units_by_key: dict[tuple[int, int], int] = {}
    taken_at_by_fridge: dict[int, datetime.datetime] = {}
    for product_stock in good_stock:
        good_units_by_key[(product_stock.fridge_id, product_stock.product_id)] = (
            product_stock.good_units
        )
        newest_taken_at = taken_at_by_fridge.get(product_stock.fridge_id, product_stock.taken_at)
        taken_at_by_fridge[product_stock.fridge_id] = max(newest_taken_at, product_stock.taken_at)
    readings = FridgeStockReadings(taken_at_by_fridge=taken_at_by_fridge)
    stale_by_fridge = readings.stale_fridge_ids(
        list(coverage_end_by_fridge),
        datetime.datetime.now(datetime.timezone.utc),
    )
    stale_fridge_ids = [fridge_id for fridge_id, is_stale in stale_by_fridge.items() if is_stale]
    return ImportFridgeStock(
        good_units_by_key=good_units_by_key,
        stale_fridge_ids=sorted(stale_fridge_ids),
    )


def _snack_drink_category_ids(
    products_by_category: dict[int, list[int]],
    session: Session,
) -> set[int]:
    category_rows = session.execute(
        select(Category).where(Category.id.in_(products_by_category))
    ).scalars()
    return {
        category.id
        for category in category_rows
        if is_target_replenish_category(category.name)
    }


def _load_snack_drink_targets(
    results: list[ForecastResult],
    session: Session,
) -> SnackDrinkTargets:
    fridge_ids = sorted({result.fridge_id for result in results})
    target_rows = session.execute(
        select(ProductTarget).where(ProductTarget.fridge_id.in_(fridge_ids))
    ).scalars()
    target_qty_by_key = {
        (target.fridge_id, target.product_id): target.target_qty for target in target_rows
    }
    return SnackDrinkTargets(
        target_qty_by_key=target_qty_by_key,
        readings=load_fridge_stock_readings(fridge_ids, session),
    )


def _target_refill_cells(
    fridge_id: int,
    product_ids: list[int],
    snack_drink_targets: SnackDrinkTargets,
) -> list[MenuGridCell]:
    cells: list[MenuGridCell] = []
    for product_id in product_ids:
        restock_qty = snack_drink_targets.restock_qty(fridge_id, product_id)
        if restock_qty > 0:
            cells.append(MenuGridCell(fridge_id=fridge_id, product_id=product_id, qty=restock_qty))
    return cells


def _stale_fridge_ids(
    fridge_stock: ImportFridgeStock,
    snack_drink_targets: SnackDrinkTargets,
    target_refill_fridge_ids: list[int],
) -> list[int]:
    """Fridges whose stock reading is too old, for the stock cut or the target refill."""
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_fridge_ids = set(fridge_stock.stale_fridge_ids)
    for fridge_id in target_refill_fridge_ids:
        if snack_drink_targets.readings.is_stale(fridge_id, now):
            stale_fridge_ids.add(fridge_id)
    return sorted(stale_fridge_ids)


def _fit_cells_to_warehouse_stock(
    cells: list[MenuGridCell],
    session: Session,
) -> MenuCellsStockFit:
    fit_lines = [
        stock_fit_service.StockFitLine(
            fridge_id=cell.fridge_id,
            product_id=cell.product_id,
            qty=cell.qty,
        )
        for cell in cells
    ]
    stock_fit = stock_fit_service.fit_lines_to_warehouse_stock(fit_lines, session)
    fitted_cells = [
        MenuGridCell(fridge_id=line.fridge_id, product_id=line.product_id, qty=line.qty)
        for line in stock_fit.lines
        if line.qty > 0
    ]
    return MenuCellsStockFit(cells=fitted_cells, cuts=stock_fit.cuts)


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
    resolve_delivery_date(year, week, day_name)  # 422 before anything is written
    scoped = category_id is not None
    existing_id = _find_menu_id(year, week, day_name, session)
    if existing_id is not None and not overwrite:
        conflict = (
            _category_has_lines(int(existing_id), category_id, session)
            if scoped
            else True
        )
        if conflict:
            raise _menu_exists_error(
                year=year,
                week=week,
                day_name=day_name,
                menu_id=int(existing_id),
                category_id=category_id,
            )

    lines_to_store = _lines_to_store(lines)
    product_ids = {line.product_id for line in lines_to_store}
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
        created_menu_id = session.execute(
            text(
                "INSERT INTO weekly_menus (year, iso_week, day_name, status) "
                "VALUES (:y, :w, :d, :status) "
                "ON CONFLICT ON CONSTRAINT uq_weekly_menus_year_week_day DO NOTHING "
                "RETURNING id"
            ),
            {"y": year, "w": week, "d": day_name, "status": MENU_STATUS_SAVED},
        ).scalar_one_or_none()
        if created_menu_id is None:
            # A concurrent save of the same key (e.g. a double click) created it first.
            raise _menu_exists_error(
                year=year,
                week=week,
                day_name=day_name,
                menu_id=None,
                category_id=category_id,
            )
        menu_id = int(created_menu_id)
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

    if lines_to_store:
        # A Core insert() batches the rows into multi-row VALUES statements; a text()
        # executemany sends one round trip per row (about a minute for a full menu).
        session.execute(
            insert(MenuLine),
            [
                {
                    "menu_id": menu_id,
                    "fridge_id": line.fridge_id,
                    "product_id": line.product_id,
                    "category_id": category_of[line.product_id],
                    "qty": line.qty,
                }
                for line in lines_to_store
            ],
        )

    _replace_week_products(
        year=year,
        week=week,
        product_ids={line.product_id for line in lines},
        category_id=category_id,
        session=session,
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
            "lines": len(lines_to_store),
        },
        user_id=user_id,
    )
    session.commit()
    return _load_grid(menu_id, year, week, day_name, session)


def _menu_exists_error(
    *,
    year: int,
    week: int,
    day_name: str,
    menu_id: int | None,
    category_id: int | None,
) -> ApiException:
    return api_error(
        409,
        "exists",
        "A saved menu already exists for this key; resend with overwrite=true",
        {
            "year": year,
            "week": week,
            "day_name": day_name,
            "menu_id": menu_id,
            "category_id": category_id,
        },
    )


def _replace_week_products(
    *,
    year: int,
    week: int,
    product_ids: set[int],
    category_id: int | None,
    session: Session,
) -> None:
    """Make the saved grid's products the week menu (only one category's part when scoped)."""
    week_menu_id = session.execute(
        text(
            "INSERT INTO weekly_menus (year, iso_week, day_name, status) "
            "VALUES (:y, :w, :d, :status) "
            "ON CONFLICT ON CONSTRAINT uq_weekly_menus_year_week_day "
            "DO UPDATE SET updated_at = now() "
            "RETURNING id"
        ),
        {"y": year, "w": week, "d": WEEK_MENU_DAY_NAME, "status": MENU_STATUS_SAVED},
    ).scalar_one()
    removal = delete(MenuProduct).where(MenuProduct.menu_id == week_menu_id)
    if category_id is not None:
        category_product_ids = select(Product.id).where(Product.category_id == category_id)
        removal = removal.where(MenuProduct.product_id.in_(category_product_ids))
    session.execute(removal.execution_options(synchronize_session=False))
    if product_ids:
        session.execute(
            insert(MenuProduct),
            [
                {"menu_id": week_menu_id, "product_id": product_id}
                for product_id in sorted(product_ids)
            ],
        )


def _lines_to_store(lines: list[MenuLineInput]) -> list[MenuLineInput]:
    """Positive lines, plus the qty-0 lines of products that have no positive line.

    A product kept on the menu with no quantity yet is stored as qty-0 lines so
    its column survives a reload; zero cells of products with quantities are
    dropped to keep ``menu_lines`` small.
    """
    products_with_quantity = {line.product_id for line in lines if line.qty > 0}
    return [
        line
        for line in lines
        if line.qty > 0 or line.product_id not in products_with_quantity
    ]


def list_stock_balances(session: Session) -> list[MenuStockBalance]:
    """Warehouse in-stock and on-order units for every product (``v_stock_balances``)."""
    rows = session.execute(
        text("SELECT product_id, physical_qty, on_order_qty FROM v_stock_balances")
    ).all()
    return [
        MenuStockBalance(
            product_id=row.product_id,
            in_stock_qty=row.physical_qty,
            on_order_qty=row.on_order_qty,
        )
        for row in rows
    ]


def _load_grid(
    menu_id: int, year: int, week: int, day_name: str, session: Session
) -> MenuGrid:
    rows = session.execute(
        text(
            "SELECT fridge_id, product_id, qty FROM menu_lines WHERE menu_id = :id"
        ),
        {"id": menu_id},
    ).all()
    cells = [
        MenuGridCell(fridge_id=row.fridge_id, product_id=row.product_id, qty=row.qty)
        for row in rows
    ]
    return _grid_from_cells(
        menu_id=menu_id,
        year=year,
        week=week,
        day_name=day_name,
        cells=cells,
        menu_product_ids=_week_product_ids(year, week, session),
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


def build_blank_menu(*, year: int, week: int, day_name: str, session: Session) -> MenuGrid:
    """An unsaved day menu: the fridges delivered on this weekday and the week menu's products."""
    return _grid_from_cells(
        menu_id=None,
        year=year,
        week=week,
        day_name=day_name,
        cells=[],
        menu_product_ids=_week_product_ids(year, week, session),
        session=session,
    )


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


def list_target_categories(session: Session) -> list[TargetCategory]:
    """Snacks and Drinks categories with their active products, in display order."""
    category_rows = session.execute(
        select(Category).order_by(Category.display_order, Category.name)
    ).scalars()
    target_categories = [
        category for category in category_rows if is_target_replenish_category(category.name)
    ]
    products_by_category = _active_products_by_category(session)
    product_ids = _flatten_product_ids(products_by_category)
    products_by_id = {product.id: product for product in _products_by_name(product_ids, session)}

    listed_categories: list[TargetCategory] = []
    for category in target_categories:
        category_product_ids = products_by_category.get(category.id, [])
        products = [
            TargetProduct(
                product_id=product_id,
                product_code=products_by_id[product_id].code,
                product_name=products_by_id[product_id].name,
            )
            for product_id in category_product_ids
        ]
        if products:
            listed_categories.append(
                TargetCategory(
                    category_id=category.id,
                    category_name=category.name,
                    products=products,
                )
            )
    return listed_categories


def copy_product_targets(
    *,
    from_fridge_id: int,
    to_fridge_id: int,
    user_id: int,
    session: Session,
) -> int:
    """Replace ``to_fridge_id``'s refill targets with ``from_fridge_id``'s; returns the count."""
    source_targets = session.execute(
        select(ProductTarget).where(ProductTarget.fridge_id == from_fridge_id)
    ).scalars()
    copied_rows = [
        {
            "fridge_id": to_fridge_id,
            "product_id": target.product_id,
            "target_qty": target.target_qty,
        }
        for target in source_targets
    ]
    session.execute(delete(ProductTarget).where(ProductTarget.fridge_id == to_fridge_id))
    if copied_rows:
        session.execute(insert(ProductTarget), copied_rows)
    record_audit(
        session,
        action="product_targets.copy",
        entity="product_targets",
        entity_id=to_fridge_id,
        after={"from_fridge_id": from_fridge_id, "targets": len(copied_rows)},
        user_id=user_id,
    )
    session.commit()
    return len(copied_rows)
