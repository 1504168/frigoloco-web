"""Pure (no database) tests: fit to stock, default rating weights, export sheet names."""

from __future__ import annotations

from decimal import Decimal

from app.services.dispatch_export_service import _unique_sheet_names
from app.services.menu_allocation_service import EVEN_WEIGHT, rating_weights
from app.services.stock_fit_service import StockFitLine, fit_lines_to_stock

PRODUCT_A = 1
PRODUCT_B = 2
FRIDGE_1 = 10
FRIDGE_2 = 20
FRIDGE_3 = 30


def test_fit_cuts_each_fridge_in_proportion_and_sums_to_stock():
    lines = [
        StockFitLine(fridge_id=FRIDGE_1, product_id=PRODUCT_A, qty=6),
        StockFitLine(fridge_id=FRIDGE_2, product_id=PRODUCT_A, qty=3),
        StockFitLine(fridge_id=FRIDGE_3, product_id=PRODUCT_A, qty=1),
        StockFitLine(fridge_id=FRIDGE_1, product_id=PRODUCT_B, qty=4),
    ]

    stock_fit = fit_lines_to_stock(lines, {PRODUCT_A: 5, PRODUCT_B: 9})

    fitted_quantities = [line.qty for line in stock_fit.lines]
    assert fitted_quantities == [3, 2, 0, 4]
    assert len(stock_fit.cuts) == 1
    product_a_cut = stock_fit.cuts[0]
    assert product_a_cut.product_id == PRODUCT_A
    assert product_a_cut.requested == 10
    assert product_a_cut.in_stock == 5
    assert product_a_cut.cut == 5


def test_fit_treats_missing_or_negative_stock_as_empty():
    lines = [
        StockFitLine(fridge_id=FRIDGE_1, product_id=PRODUCT_A, qty=2),
        StockFitLine(fridge_id=FRIDGE_1, product_id=PRODUCT_B, qty=2),
    ]

    stock_fit = fit_lines_to_stock(lines, {PRODUCT_B: -3})

    assert [line.qty for line in stock_fit.lines] == [0, 0]
    assert [cut.cut for cut in stock_fit.cuts] == [2, 2]


def test_fit_never_gives_a_fridge_more_than_it_asked():
    lines = [
        StockFitLine(fridge_id=FRIDGE_1, product_id=PRODUCT_A, qty=1),
        StockFitLine(fridge_id=FRIDGE_2, product_id=PRODUCT_A, qty=1),
        StockFitLine(fridge_id=FRIDGE_3, product_id=PRODUCT_A, qty=1),
    ]

    stock_fit = fit_lines_to_stock(lines, {PRODUCT_A: 2})

    fitted_quantities = [line.qty for line in stock_fit.lines]
    assert sum(fitted_quantities) == 2
    assert max(fitted_quantities) == 1


def test_unscored_product_weighs_the_category_mean_score():
    scores = {PRODUCT_A: Decimal("0.8"), PRODUCT_B: Decimal("0.4")}
    unscored_product = 3

    category_weights = rating_weights([PRODUCT_A, PRODUCT_B, unscored_product], scores)

    assert category_weights.weights == [Decimal("0.8"), Decimal("0.4"), Decimal("0.6")]
    assert category_weights.default_score_product_ids == [unscored_product]


def test_category_without_scores_is_split_evenly():
    category_weights = rating_weights([PRODUCT_A, PRODUCT_B], {})

    assert category_weights.weights == [EVEN_WEIGHT, EVEN_WEIGHT]
    assert category_weights.default_score_product_ids == [PRODUCT_A, PRODUCT_B]


def test_client_sheet_names_are_valid_and_unique():
    long_name = "A client name that is far too long for Excel"

    sheet_names = _unique_sheet_names(
        ["Acme/Group", "acme group", long_name, "Fridge x Product"],
        taken=["Dispatch lines", "Fridge x Product"],
    )

    assert sheet_names[0] == "Acme Group"
    assert sheet_names[1] == "acme group (2)"
    assert len(sheet_names[2]) == 31
    assert sheet_names[3] == "Fridge x Product (2)"
