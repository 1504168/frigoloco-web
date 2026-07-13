# Deck-guidance audit: schema.sql vs FrigoLoco_Dev_Presentation_V5_Final.pptx

Audited 2026-07-03 (verifier session) against the fully-extracted deck (24 slides) and the verified Intelligent Fridges OpenAPI spec (`specs/0004-.../reference-docs/intelligentfridges_openapi_v1.json`).

## Confirmed covered (no action)

- **Slide 12/23/24 non-negotiables**: append-only `stock_movements` with `trg_stock_non_negative` (advisory-lock serialised) and append-only trigger; `audit_log`; user+timestamp columns throughout. This is the deck's "before any other feature" item - done.
- Slide 10 category print order → `categories.dispatch_print_order`.
- Slide 21/24: `products.code` TEXT (leading zeros), nullable `shelf_life_days` with 218-product backfill note, `if-XXXXXXX` fridge id kept alongside friendly name.
- Slide 13: `clients.workers_count` / `worker_type` / preferences.

## Gaps vs deck (action suggested)

1. **Slide 23 - "Import loses product order → preserve left-to-right source order; never sort alphabetically."**
   `products` has no order column and `menu_products` has no per-menu position. Suggest `products.display_order INTEGER` (source column order; spec 0004's product table now carries this) and/or a `position` column on `menu_products` so menu/dispatch-matrix column order round-trips. Without it, every product listing will default to alphabetical/id order - exactly the Excel bug the deck says not to replicate.

2. **Money units diverge from the verified API contract. - RESOLVED 2026-07-03 (migration 0002).**
   `schema.sql` used `NUMERIC(10,2)` euros; the Husky API returns **`int64` minor units (cents)** for every price field (verified in the OpenAPI spec), and `CLAUDE.md` + spec 0004 standardise on integer-cents `bigint`. Two conventions in one database guarantees a factor-100 bug eventually. **Converged on integer cents:** every money column is now `BIGINT` minor units (see finding 9 below); euros exist only at the API presentation edge (unchanged 2-decimal euro-string JSON).

3. **Slide 4 step 6 - weather-adjusted forecasting (18 months of weather/sales correlation).**
   No weather table or ingestion job exists in any artifact. Raised as open question Q11 in spec 0004 (defer to forecast spec vs add `weather_observation` + backfill now). Deferring is safe - historical weather is always retrievable later, unlike stock snapshots.

## FYI

- Spec numbering: this session's DB+backfill spec was renumbered **0001 → 0004** to avoid colliding with specs 0001–0003; SPEC_LOG.html updated.
- `mockups/REVIEW-returns-mockup.md` contains the returns-mockup verification (weekly food-cost basis + POS fee base errors).

## Post-implementation findings (verifier, 2026-07-03, after live Husky sync)

4. **`categories` seed numbering was wrong vs the vendor taxonomy.** Husky's real `productCategory` values are: 1. Cold Dishes, 2. Wraps & Sandwiches, 3. Warm Dishes Jar, 4. Warm Dishes, 5. Desserts, 6. Snacks, 7. Drinks, 8. Breakfast, 9. Soup, 10. Frozen Warm Dishes. The seed had e.g. "2. Warm Dishes"/"4. Wraps & Sandwiches" swapped and "5. Breakfast & Granolas"/"8. Drinks" misplaced. **Fixed live in the Railway DB** (empty seed rows deleted; vendor rows renumbered; deck print order Hot→Frozen→Salads→Wraps→Granolas→Soups→Desserts→Drinks→Snacks preserved via `dispatch_print_order`; +`Uncategorised` catch-all). **Update the seed block in schema.sql to match** so a fresh apply doesn't recreate the drift.
5. **`clients` had no natural unique key** → upserts couldn't ON CONFLICT. **Added live:** `uq_clients_name UNIQUE (name)`. Mirror it in schema.sql.
6. **`restock_action` enum lacks `unchanged`** and `restock_events.product_id` is NOT NULL - so UNCHANGED tag events (5,020 of 6,626 in a 48h window) and UNRECOGNISED tags (no productCode) cannot be stored. Fine for now; the deck's residual-stock/withdrawal features may need them later.
7. **`product_reviews.husky_ref`**: vendor exposes no review id; sync synthesizes a deterministic ref (productCode|fridge|date|rating|purchaseId).
8. **Husky report endpoints reject `to` within the last ~5 minutes** and fractional-second timestamps - sync clamps report windows to now−6min (handled in cron/_base.py).
9. **Money migrated to integer cents (user decision 2026-07-03).** Every monetary column (`products.purchase_price/sales_price`, `fridge_product_prices.sales_price`, `client_fees.yearly_fee`, `client_service_charges.amount`, `purchase_orders.total_*`, `purchase_order_lines.unit_price`, `dispatch_lines.unit_*_price`, `sales_events.unit_price/discount_amount`, `restock_verification_lines.diff_value`, `weekly_financials` money inputs + `rfid_fee_snapshot`) converted `NUMERIC(10,2)` euros → `BIGINT` minor units via `round(c*100)` in `backend/scripts/migrations/0002_money_to_cents.sql` (idempotent, applied to the live Railway DB). `settings.rfid_fee_eur` value 0.10 → 10 (cents); `pos_fee_pct` stays a fraction. VAT rates, `pos_fee_pct_snapshot`, `forecast_qty` and `*_score` columns stay `NUMERIC` (fractions/quantities, not money). Services compute in integer cents; the API still emits 2-decimal euro strings (`app/money.py`), so the frontend is untouched.
