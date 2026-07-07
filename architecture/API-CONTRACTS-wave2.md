# API Contracts — Workflow/Reports/Sync wave (for frontend agents)

> Verified live on http://localhost:8100 (2026-07-03). Error envelope everywhere: `{"error":{code,message,details}}`; money = euro strings; overwrite conflicts = `409 {code:"exists"}`.

## Pipeline (year, week, day_name) — day_name Monday..Sunday case-insensitive

**Forecast**
- `POST /api/v1/forecasts/run` body `{delivery_date, fridge_ids?, model?="moving_average_3w", params?}` → ForecastRunOut
- `POST /api/v1/forecasts/save` body `{year, week, day_name, fridge_ids?, model?, params?, overwrite?=false}` → ForecastRunOut | 409 exists
- `GET /api/v1/forecasts/saved?year&week&day_name` → ForecastRunOut | 404
- `GET /api/v1/forecasts/actuals?year&week&day_name` → ForecastActualsOut — Added/Sold/% side block over the SAME 3-week lookback window as the forecast run (for the "%adjust"/actuals column).
- ForecastRunOut: `{run_id, delivery_date, iso_year, week_no, day_name, run_at, model, is_saved, params, results:[{fridge_id, category_id, forecast_qty, valid_days, holiday_days}]}`
- ForecastActualsOut: `{year, week, day_name, delivery_date, window_start, window_end (exclusive), cells:[{fridge_id, category_id, added_qty, sold_qty, ratio (sold/added fraction, null when added=0)}]}`

**Menu**
- `POST /api/v1/menus/import-from-forecast?year&week&day_name` → MenuGridOut (preview) | 404
- `POST /api/v1/menus/save` body `{year, week, day_name, lines:[{fridge_id, product_id, qty>=0}], overwrite?}` → MenuGridOut | 409 exists
- `GET /api/v1/menus/saved?year&week&day_name` → MenuGridOut | 404
- `POST /api/v1/menus/draft-purchase-orders?year&week&day_name&supplier_id` → PurchaseOrderRead | 404/422 (drafts one PO per supplier from the saved menu's quantities)
  - PurchaseOrderRead lines are `PurchaseOrderLineRead`: `{id, product_id, product_code, product_name, qty_ordered, qty_received, unit_price, vat_rate, line_ex_vat, line_vat, line_incl_vat}` — `product_code`/`product_name` are embedded from the products join so the PO detail UI shows code/name, not a bare id.
- MenuGridOut: `{menu_id, year, week, day_name, fridges:[{fridge_id,friendly_name}], products:[{product_id,product_name,category_id}], categories:[{category_id,category_name,product_ids[]}], cells:[{fridge_id,product_id,qty}]}`

**Dispatch**
- `POST /api/v1/dispatches/import-from-menu?year&week&day_name` → DispatchMatrix (dispatch_id:0 = preview) | 404
- `POST /api/v1/dispatches/save` body `{year, week, day_name, lines:[{fridge_id, product_id, qty>0, source?}], overwrite?}` → DispatchRead status "saved" (NO stock) | 409 exists | 409 conflict (already dispatched)
- `GET /api/v1/dispatches/saved?year&week&day_name` → DispatchRead | 404
- `POST /api/v1/dispatches/create-individual?year&week&day_name&force=false` → `{dispatch_id, status:"dispatched", movements_created}` | 409 stock_blocked | 409 past_date_requires_force

**Stock**
- `POST /api/v1/stock/opening-stock` body `{product_id, qty>0, reason}` → MovementOut 201 | 409 stock_blocked

## Reports / Rating
- `GET /api/v1/finance/fridge-report?fridge_id&from&to` → `{fridge_id, date_from, date_to, added_qty, food_cost, revenue, margin, margin_pct, rows:[{product_id, code, name, category, added_qty, unit_buying_price, unit_selling_price}]}`
- `GET /api/v1/finance/fridge-report/export.xlsx?fridge_id&from&to` → xlsx download (Content-Disposition filename). Frontend: trigger download via anchor/blob.
- `GET /api/v1/rating/scorecard?limit&offset&window_days=365&sort="final_score desc"` → `{items:[18-column scorecard rows], total, limit, offset, window_days, period_end, weights:{pct_sold,margin,review}}`. Sortable: final_score,name,code,category,brand,buying_price,sold_price,vat_rate,profit_margin,total_sold_qty,total_added_qty,pct_sold,positive_reviews,negative_reviews,pct_positive_review,shelf_life_days. Bad sort → 422.

## Finance — weekly inputs (manual)
- `GET /api/v1/finance/weekly/{year}/{week}` → WeeklyPnlRead — the manual `inputs` block plus computed KPIs.
- `PUT /api/v1/finance/weekly/{year}/{week}` body `WeeklyFinancialInputs` `{catering_turnover, catering_food_cost, tgtg_turnover, logistics_cost (all money = euro strings), drops_count, unsold_items, fridge_count?, remarks?}` → WeeklyPnlRead. `fridge_count` is the manual per-week fridge count (nullable = "not entered this week", non-negative when present).
- WeeklyPnlRead.inputs (WeeklyInputsRead): `{catering_turnover, catering_food_cost, tgtg_turnover, logistics_cost, drops_count, unsold_items, fridge_count, remarks}` (money fields as euro strings).

## Settings (generic key/value tunables, JSONB)
- `GET /api/v1/settings` → `[{key, value (JSON), description, updated_at}]` (sorted by key).
- `PUT /api/v1/settings/{key}` body `{value (JSON), description?}` → the upserted SettingRead.
- `menu_category_columns` — configurable minimum column slots per category for the Menu/Dispatch grids. Value is a positive integer (JSON number); the frontend falls back to `6` when the setting is absent or non-numeric.

## Husky sync + status override
- `POST /api/v1/sync/husky/{feed}` feed ∈ catalogue|prices|purchases|restock|reviews|stock|all → instant `{sync_run_id, feed, endpoint, status:"running", window_from, window_to}`; UI polls runs. Catalogue takes ~2–3 min.
- `GET /api/v1/sync/runs?endpoint&limit` → Page<SyncRunRead> newest-first (`endpoint` values: catalogue, fridgeproductprice, purchases, restock, productreview, stock_current, all).
- Products & Fridges rows now include `local_status` (null|"inactive"|"cancelled") + `effective_status` ("active"|"inactive"|"cancelled"). Set override via existing PUT with `local_status` (explicit null = follow Husky). Lists accept `?status=active|inactive|cancelled|all`. Badge from `effective_status`. Caption: "Active follows Husky sync; Inactive/Cancelled are manual overrides that survive every sync."
