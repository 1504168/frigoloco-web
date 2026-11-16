# 0009 - Stock-aware replenishment for the menu import

## Modification History

| Date (UTC)              | Description |
|-------------------------|-------------|
| 2026-10-28 09:14 AM UTC | Initial creation: Part A (per-product fridge-stock cut) built; Part B (slow-sales pace cut) planned, waiting on thresholds. |
| 2026-10-28 09:40 AM UTC | Part B approved with thresholds 5 units / 70% / 50% and built behind its own switch. |

## Parent Spec

`specs/0008-weekly-menu-and-sold-first-replenishment_2026-10-22_0950AM_UTC/` - the
menu import that splits each fridge x category forecast over the week menu's products
(by rating, optionally sold-first). This spec changes only how that split ends.

## Why

Meeting of 22 Oct 2026 (Mathieu): the menu import ignores what is still in each fridge
per product. The forecast already deducts good in-fridge stock per CATEGORY, but the
split over products does not know which products that stock belongs to. Example:
Salads forecast 10, Caesar still has 3 good units in the fridge, yet Caesar gets its full
rating share. Drivers then carry Caesars to a fridge that is full of them, while the
other salads run short.

Second ask (Part B): a fridge whose category is selling clearly slower than its last
forecast expected keeps getting the full forecast, so stock piles up and expires.

## Part A - Per-product fridge-stock cut (built)

### Rule

For each fridge x category in the import (all categories, Snacks and Drinks included):

1. `good_p` = units of product `p` in the fridge that do not expire before the fridge's
   next delivery (`delivery_date + days_to_fill`), from the latest `fridge_stock`
   reading, read fresh at import time. A unit whose tag has no expiry date counts as
   good.
2. `gross` = saved forecast qty + `sum(good_p)` over the menu products of the category,
   but only when the saved forecast run deducted residual stock
   (`params.residual_deduction`); otherwise `gross` = saved forecast qty.
3. Split `gross` with the existing logic (sold-first, then rating) into `share_p`.
4. `qty_p = max(share_p - good_p, 0)`. A well-stocked product can drop to 0.

The switch "Use fridge stock" on the Menu page turns it on. It defaults off on Monday
(fresh start) and on every other day, like "Sold first". When off, or when the delivery
is not the next one for its weekday (stock is only known now), the import is exactly
as before.

### Why add back only the menu products' stock (trade-off)

The saved forecast is already net of the category's good stock, so cutting per product
on top of it would subtract the same units twice. Options considered:

| Option | Effect | Verdict |
|---|---|---|
| Cut per product from the net forecast | Menu products' stock subtracted twice | Rejected: under-delivers |
| Add back ALL category stock, then cut per product | Off-menu products' stock (last week's dish still in the fridge) is added back but never cut again: over-delivers by those units | Rejected |
| **Add back only the menu products' stock, then cut per product** | Off-menu stock stays deducted once (by the forecast, at category level); menu products' stock is deducted once (per product) | **Chosen** |

With the chosen rule the total delivered equals the net forecast whenever no product
holds more than its share; when one is overstocked it gets 0 and the others keep their
share, so the total can be above the net forecast. That is deliberate (decision 1: a
well-stocked product can drop to 0 without starving the rest of the category).

Known limits:

- The add-back uses the stock read NOW, while the forecast deducted the stock read when
  it ran. If units sold in between, the add-back is a little lower than what was
  deducted. The import normally follows the forecast closely.
- When the forecast clamped a category at 0 (more stock than demand), the true gross
  is unknown; the add-back can then slightly over-state demand.
- A forecast that deducted nothing (delivery more than 7 days ahead when it ran) gets
  no add-back, and off-menu stock is then not deducted at all.

### Units with no expiry date (decision 2)

They now count as good stock, both in the per-product cut and in the forecast residual
deduction, so both use one rule (`app/services/fridge_stock_service.py`). Previously the
forecast skipped them to avoid over-deducting. `fridge_stock.units` is the
authoritative count; `expiry_dates` lists only the tags that carry a date.

### Stale readings

If a fridge's newest reading is missing or older than `STOCK_READING_MAX_AGE` (2 h, the
constant of the allocation route, reused), the import still uses its last-known units
and returns the fridge in `stale_stock_fridge_ids`; the Menu page shows a warning.

### API (backward compatible)

- Request `MenuImportRequest.use_fridge_stock: bool = false`.
- Response adds `fridge_stock_applied`, `stale_stock_fridge_ids`, and `stock_cuts`
  (`fridge_id`, `product_id`, `in_fridge_units`, `reduced_by`) for every menu product
  with good units in a fridge. Each grid cell with data gets the tooltip
  "In fridge: 3 - reduced by 3".

## Part B - Slow-sales pace cut (built)

### Rule

Per fridge x category, before the product split:

- Previous delivery = the category's last restock ADDED event in the fridge within 14
  days before the delivery day (the sold-first notion of "last delivery").
- `expected` = that delivery date's saved forecast qty x (elapsed selling time since
  the delivery / selling days of its `days_to_fill` window), capped at the whole
  window. Elapsed time runs to now, never past the new delivery day. Weekend days do
  not count for a fridge with `active_on_weekends = false`.
- `actual` = non-refunded sales of the category in the fridge since that delivery.
- `pace = actual / expected`.
- If `expected < 5` units: no cut (too little to judge). If `pace < 0.70`:
  `factor = max(pace, 0.50)`, else `factor = 1`.
- New category qty = `round_half_up(qty x factor)` to whole units. When Part A is on,
  the factor scales the gross demand (forecast + added-back stock) and the stock is
  taken off afterwards, because slow sales lower demand, not stock.

| Constant | Value | Why |
|---|---|---|
| `MIN_EXPECTED_UNITS_FOR_PACE_CUT` | 5 | Below 5 expected units one sale more or less swings the pace by 20%+, so the signal is noise. |
| `SLOW_SALES_THRESHOLD` | 0.70 | A category selling under 70% of plan is clearly slow; normal day-to-day variance stays above it. |
| `SLOW_SALES_FLOOR` | 0.50 | Never cut more than half: a slow week must not empty the fridge, and the next forecast still learns from the sales. |

No previous saved forecast, no delivery config for that weekday, or no delivery in the
lookback: no cut. The fill window and weekend flag come from the current delivery
config, not from the old run's snapshot (simpler, and configs rarely change).

Known limit: the previous saved forecast is itself net of residual stock, so `expected`
can be lower than the real expected sales, which makes the cut more conservative.

### Switch

A separate switch "Slow-sales cut", same default as the others, so each effect can be
seen alone. Off: identical to before.

### API

- Request `MenuImportRequest.slow_sales_cut: bool = false`.
- Response `sales_pace_cuts` (`fridge_id`, `category_id`, `expected_units`,
  `sold_units`, `pace`, `factor`) for each applied cut. The Menu page lists them in a
  compact notice ("Fridge A Salads: sold 6 of expected 10 (60%), forecast cut to 60%")
  and as a tooltip on that fridge's cells of the category.

## Files

- `backend/app/services/fridge_stock_service.py` (new): shared good-units query.
- `backend/app/services/sales_pace_service.py` (new): Part B.
- `backend/app/services/replenishment_service.py`: `cut_by_fridge_stock`, shared
  last-delivery SQL, category sales since last delivery.
- `backend/app/services/forecast_service.py`: residual uses the shared query;
  `is_next_delivery`, `is_selling_day`, `count_selling_days` made public.
- `backend/app/services/menu_service.py`, `backend/app/schemas/menus.py`,
  `backend/app/routers/menus.py`: switches and response fields.
- `frontend/src/pages/ops/menu/*`, `PlanningGrid.tsx`, `lib/types.ts`, `lib/grid.ts`.
- No schema change.
