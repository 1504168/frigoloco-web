# REWORK-VALIDATION — D1–D6 Critic + QA Pass

> Validator session, 2026-07-03. Backend live on `:8100`, frontend on `:5173`, DB = Railway PostgreSQL 18.4.
> Method mix: **live API calls** (synthetic key **2027-W3** only), **direct DB queries** (read-only helper against the app's own `DB_URL`), and **code reads** (5 parallel Explore agents, evidence cited by `file:line`).
> No production data was mutated. All synthetic rows created during testing were removed (see §5). Stock was never touched (`stock_movements` held at 8 throughout; `v_stock_balances` unchanged).

---

## 1. Coverage Table

Legend: **PASS** = requirement met and verified · **PARTIAL** = substance present with a real gap/deviation · **FAIL** = not met.

| WO item | Where implemented | How verified | Status |
|---|---|---|---|
| **D1.1** No PG enum binding | `models/enums.py:34-40` `text_enum()` (`native_enum=False`); migration `0003_enums_to_text.sql`; named `chk_*` CHECKs on all 9 enum cols | DB: `pg_type` shows **0** enum types remain; code read; CHECK audit | **PASS** |
| **D1.2** `dispatch_lines` partitioned | `models/operations.py:180-229` (`RANGE (delivery_date)`, PK incl. `delivery_date`); `0004_partition_dispatch_lines.sql`; `create_next_month_event_partitions()` in schema.sql:619-651 | DB: `pg_partitioned_table` = RANGE, **36** monthly partitions 2025-01…2027-12; code read | **PARTIAL** — maintenance function exists but **no scheduled caller** (no cron job invokes it); cron README stale |
| **D1.3** Full model/CHECK pass | CHECK constraints across all tables; money = BIGINT cents; `schema.sql` | DB CHECK audit (60 constraints); code read | **PARTIAL** — see §4 items 3,5,10 (ORM drift, missing `dispatch_lines.vat_rate` bound, schema.sql under-naming) |
| **D2 Forecast** run/save/409/overwrite/saved | `routers/forecasts.py`; `services/forecast_service.py:265-393` | **Live**: run→200 `is_saved=false` (0 saved rows persisted), save→200, dup→**409 `exists`**, overwrite→200, saved→200 | **PASS** |
| **D2 Menu** import/save/saved + score allocation | `routers/menus.py`; `services/menu_service.py`, `menu_allocation_service.py` | **Live**: menu save→200; import-from-forecast→200; code read (largest-remainder by score) | **PASS** |
| **D2 Dispatch** import/save=PLANNED/create-individual | `routers/dispatches.py`; `services/dispatch_service.py:531-679` | **Live**: import preview `dispatch_id=0`; save→200 `status="saved"`, **stock unchanged**; code read (confirm writes negative movements only in `confirm_dispatch`) | **PASS** |
| **D2 Orders** draft-from-menu per supplier | `routers/menus.py:165-190` `/menus/draft-purchase-orders`; `menu_service.py:386-410` | Code read | **PARTIAL** — route named `/menus/draft-purchase-orders`, **not** the `/purchase-orders/draft-from-menu` in the contract doc (doc drift) |
| **D2 Stock** derived only + opening-stock | `services/stock_service.py`; `routers/stock.py:66-80` | **Live**: `STOCK_UNCHANGED=true` across menu+dispatch save; code read (only `confirm_dispatch`, `record_adjustment`, PO receipt/cancel write movements) | **PASS** |
| **D3 Fridge Report** (rename GSV) | `routers/finance.py:55-63`; `finance_service.py:599-679` | **Live** export + code read | **PASS** — internal identifier `get_fridge_gsv_report` still says "GSV" (cosmetic, not in API/output) |
| **D3 export.xlsx** (Polars body + openpyxl summary-top) | `services/report_export_service.py:23-142` | **Live**: downloaded xlsx — sheet "Fridge Report", summary rows 1-9, table header row 11 | **PASS** |
| **D3 Scorecard** 18 cols + weights | `routers/rating.py`; `finance_service.py:794-848` | **Live**: 18 cols returned, weights present; **hand-checked product 121 = 0.9519** against raw DB facts | **PASS** |
| **D3 Supplier info** email + warehouse | `models/master.py:57-63`; `schemas/masters.py:182-200` | Code read | **PASS** — single `email` field (not a multi-value "order emails" list) |
| **D4.1** week/day selectors + pipeline buttons | `ops/components/WeekDayPicker.tsx`; Forecast/Menu/Dispatch pages | Code read | **PASS** — "Load saved" label vs "Import from Saved" (cosmetic) |
| **D4.2** Excel-like menu grid + client-side cascading pickers | `ops/components/PlanningGrid.tsx`, `AddProductPicker.tsx`; `ops/lib/reference.ts` | Code read | **PARTIAL** — **"stock & ordered" detail row missing** |
| **D4.3** configurable columns-per-category | `ops/lib/reference.ts:20-21`; `SettingsPage.tsx` | Code read | **PASS** — via generic "Other" settings editor |
| **D4.4** Forecast-V2 page | `ops/forecast/ForecastPage.tsx` | Code read | **PARTIAL** — **"%adjust" row missing** in the forecast grid |
| **D4.5** Fridge Report page | `finance/FridgeReportCard.tsx` | Code read + live export button target | **PASS** — rendered as a card in Finance, not a standalone route |
| **D4.6** Product Rating page | `rating/RatingPage.tsx` | Code read | **PARTIAL** — action labeled **"Recompute"**, not "Update Rating" |
| **D4.7** states + scroll containment | shared `LoadingSkeleton/EmptyState/ErrorState`; `overflow-x-auto` wrappers | Grep + code read | **PASS** |
| **D5.1** ownership contract + local_status | `husky/sync.py:110-206` whitelist guard; `0006_local_status.sql` | **Live**: override survives simulated husky upsert; guard raises `SyncContractError` on `local_status`; API bad→422; DB→CheckViolation; effective_status flips | **PASS** — local-owned doc tuple lists only `local_status`+delivery fields (mechanism covers all) |
| **D5.2** sync relocation, no cycle | `backend/app/husky/sync.py`; cron jobs thin wrappers | Code read (no `import cron` in backend) | **PASS** |
| **D5.3** sync API (trigger + runs) | `routers/husky_sync.py:101-145` | Code read | **PASS** |
| **D5.4** frontend sync UI | `masters/sync/*`, `SyncPage.tsx`, `ProductsPage.tsx`, `FridgesPage.tsx` | Code read | **PASS** |
| **D5.5** frontend re-validation | — | **Live**: `npm run build` clean, all 13 routes 200, grids `overflow-x` contained | **PASS** |
| **D6.1** brand teal primary | `index.css` `--brand-teal:#45bcb4`, `--brand-teal-aa:#1a8175`, `--primary→--series-1` | Grep | **PASS** — navy sidebar (`#14202e`) + teal accent |
| **D6.2** sidebar brand block + collapsed pin | `Sidebar.tsx:36`; `public/frigoloco-logo.svg` | Code read | **PARTIAL** — **collapsed pin-only mark not implemented** (sidebar is fixed-width, no collapse) |
| **D6.3** favicon pin on teal | `public/favicon.svg`; `index.html:5` | File + grep | **PASS** |
| **D6.4** login/empty/export headers inherit brand | empty states via tokens | Code read | **PARTIAL/deferred** — no login screen; export headers not brand-stamped (WO says "later") |
| **D6.5** ASK ISMAIL: drop real logo | placeholder `frigoloco-logo.svg` committed | — | **N/A** (user action) |

---

## 2. Functional Validation — Live API Calls (synthetic key 2027-W3)

All calls against `http://localhost:8100/api/v1`. Delivery date `2027-01-18` (ISO 2027-W03 Monday, weekday 1).

### 2a. Pipeline: run → save → 409 → overwrite → menu import → save → dispatch save
The Forecast stage is **gated in production** by an empty `fridge_delivery_config` (see §4-1): a bare `POST /forecasts/run` returns **409 `no_delivery_config`**. To validate the run/save/overwrite semantics I inserted a **temporary** config row for fridge 1 / weekday 1, ran the test, and deleted it (guaranteed cleanup in a `finally`).

| Step | Result |
|---|---|
| `POST /forecasts/run` | 200, `is_saved=false`, 11 results, **0 saved rows persisted** (no auto-save) ✅ |
| `POST /forecasts/save` | 200, `is_saved=true` ✅ |
| `POST /forecasts/save` (dup) | **409 `{code:"exists"}`** ✅ |
| `POST /forecasts/save?overwrite=true` | 200, `is_saved=true` (atomic delete+reinsert) ✅ |
| `GET /forecasts/saved` | 200, 11 results ✅ |
| `POST /menus/import-from-forecast` | 200 (structurally OK; 0 cells — no product scores/history for this key) ✅ |
| `POST /menus/save` | 200, `menu_id` created ✅ |
| `POST /dispatches/import-from-menu` | 200, preview `dispatch_id=0` ✅ |
| `POST /dispatches/save` | 200, **`status="saved"`** ✅ |
| **`v_stock_balances` + `stock_movements`** | **UNCHANGED** before/after (movements stayed at 8) ✅ — confirms save path never deducts stock |

### 2b. Sync ownership (override survives sync)
Faithful to the WO but **safe**: I created a synthetic **ZZTEST** product, exercised the override lifecycle live, and proved preservation via the **real** guard rather than triggering a 2-3 min external catalogue pull that would rewrite ~1,000 real products mid-validation.

- `POST /products` → 201, `effective_status="active"`.
- `PUT local_status="cancelled"` → `effective_status="cancelled"` ✅.
- Guard: `_ALLOWED_UPDATE_COLUMNS["products"]` **excludes `local_status`**; `_guarded_update_set(products, {…, local_status})` raises **`SyncContractError`** ✅.
- Simulated husky upsert (`UPDATE` husky-owned cols name/price/is_active, as sync does) → **`local_status="cancelled"` survived** (`OVERRIDE_SURVIVED=true`) ✅.
- `PUT local_status=null` → `effective_status="active"` (revert) ✅. Product **deleted** (204).

### 2c. Enum CHECK rejection
- API: `PUT /products/{id}` `local_status="bogus"` → **422 `validation_error`** (Pydantic `Literal`).
- DB: raw `UPDATE … local_status='bogus'` → **`CheckViolation`** (`chk_products_local_status_values`).
- Model enum: `POST /forecasts/run` `model="definitely_not_a_model"` → **422**.

### 2d. Scorecard math hand-check — product 121 "Chocolate Chip Cookies"
Raw DB facts (365-day window ending 2026-07-03): sold=10591, added=11431, pos=113, neg=3, sold_price €2.45, vat 0.06, **buy €0.00**. Weights 0.62/0.33/0.05.
- pct_sold = 10591/11431 = **0.9265** ✅ (matches API)
- margin = (2.45/1.06 − 0)/(2.45/1.06) = **1.0000** ✅ (degenerate — buy=0)
- review = (113−3)/(113+3) = 0.9483; pct_positive = 113/116 = **0.9741** ✅
- final = 0.62·0.9265 + 0.33·1.0 + 0.05·0.9483 = **0.9519** ✅ (matches API exactly)

### 2e. export.xlsx headers
`GET /finance/fridge-report/export.xlsx?fridge_id=1&…` → `Content-Type` xlsx, `Content-Disposition` filename set. Sheet **"Fridge Report"**; **summary first** (rows 1-9: title, Fridge, Period, Total Added Qty, Food Cost, Revenue, Food Margin, Food Margin %); **table below** (row 11 headers: Product · Code · Category · Added Qty · Unit Buying Price · Unit Selling Price). ✅ (Food Cost=0 / Margin=100% is a data artifact — see §4-2.)

---

## 3. Aesthetic / Frontend Checks

- **Brand tokens** (`src/index.css`): `--brand-teal: #45bcb4`, `--brand-teal-aa: #1a8175`, `--sidebar-accent: #45bcb4`; `--primary → --series-1 → brand teal` (AA-dark in light mode, full teal in dark). ✅
- **Sidebar logo block**: `<img src="/frigoloco-logo.svg">` at `Sidebar.tsx:36` with text-wordmark fallback; navy panel + teal accent bar. ✅ (collapsed pin-only mark **not** implemented — §4-8.)
- **Favicon**: `public/favicon.svg` = white pin on `#45BCB4`, referenced `index.html:5`. ✅
- **Grid overflow containers**: `overflow-x` present in `PlanningGrid.tsx`, `ForecastPage.tsx`, `FridgeReportCard.tsx`, `RatingPage.tsx`, `SyncPage.tsx`, `MonthlyView.tsx`, `VerificationsPage.tsx`, `ui/table.tsx` — page body does not scroll sideways. ✅
- **All routes 200**: `/ /forecast /menu /dispatch /rating /finance /masters/products /masters/sync /masters/fridges /purchase-orders /stock /alerts /settings` — all **200**. ✅
- **`npm run build`**: clean (`tsc -b && vite build` succeeded, 2530 modules). Only warning: JS bundle **629 kB > 500 kB** (no code-splitting) — §4-11. ✅
- **Placeholders**: `placeholderRoutes` empty; `PlaceholderPage` used only for the `*` 404 catch-all. No leftover feature placeholders. ✅

---

## 4. Ranked Residual Findings

> Severity reflects production impact. None block the save-path stock invariant, which holds.

**1. [HIGH · data gap] `fridge_delivery_config` is empty (0 rows) → Forecast pipeline non-functional.**
Artifact: `fridge_delivery_config` table; `forecast_service`. Scenario: any real `POST /forecasts/run` returns **409 `no_delivery_config`**, so Menu import-from-forecast (and the whole Forecast→Menu→Dispatch chain from the forecast side) cannot run until config is seeded. Graceful failure, but the feature is dark in prod. Proportionate fix: seed `min_daily_qty`/`days_to_fill` per fridge×weekday (bulk import or an opening data-entry screen); until then the Forecast page will only ever 409.

**2. [HIGH · data gap] All 1,017 products have `purchase_price = 0`.**
Artifact: `products.purchase_price`. Scenario: (a) Fridge Report **Food Cost = €0** and **Food Margin = 100%** for every fridge — the report is misleading; (b) scorecard **margin component is a constant 1.0** for every product with a sale price, so the 0.33 margin weight collapses to a fixed +0.33 offset and contributes **nothing** to product ranking — rankings are effectively driven by pct_sold + review only. Proportionate fix: confirm whether Husky provides cost prices; if yes, map them in `sync.py` (currently `purchase_price` is in the husky-owned set but arriving as 0); if not, provide a manual cost-entry path. Highest-value single fix for report/scorecard fidelity.

**3. [MED · code] Planning ORM models drifted behind `schema.sql`/migration 0005.**
Artifact: `models/planning.py`. `ForecastRun` lacks `model`/`is_saved`/`day_name`; `WeeklyMenu` keeps the dropped `uq_weekly_menus_year_week` and lacks `day_name`; `menu_lines` has **no ORM model** at all. Live endpoints work because the services use raw SQL, so this is latent — but any future ORM use of these entities will error or write wrong keys. Fix: reconcile the models with schema.sql/0005 and add a `MenuLine` model.

**4. [MED · ops] Partition-maintenance duty not scheduled.**
Artifact: `create_next_month_event_partitions()` (schema.sql:619-651) has **no caller** — no APScheduler job in `cron/cron/scheduler.py`, and `architecture/cron/README.md` documents a `partition_maintenance` cron that is unimplemented and names only sales/restock (not `dispatch_lines`). Scenario: inserts dated **after 2027-12** into `dispatch_lines`/`sales_events`/`restock_events` will fail with "no partition found". Fix: wire a monthly job calling the function; correct the README.

**5. [LOW-MED · schema] `dispatch_lines.vat_rate` missing the `[0,1)` CHECK** the WO asked for on fraction columns (present on `products.vat_rate` and `purchase_order_lines.vat_rate`). `weekly_financials.pos_fee_pct_snapshot` likewise unbounded. Fix: add named `chk_dispatch_lines_vat_rate` `>=0 AND <1`.

**6. [LOW · frontend] D4 grid/label gaps.** "stock & ordered" detail row missing in the menu grid (`PlanningGrid.tsx`/`ProductMeta`); "%adjust" row missing in the Forecast grid (`ForecastPage.tsx`); Rating action labeled "Recompute" not "Update Rating"; Fridge Report is a card inside Finance rather than a standalone route; "Load saved" vs "Import from Saved" wording. Proportionate fixes: add the two missing rows (functional), rename the button (cosmetic).

**7. [LOW · doc drift] `API-CONTRACTS-wave2.md` names `POST /purchase-orders/draft-from-menu`; the actual route is `POST /menus/draft-purchase-orders`.** Also the internal `get_fridge_gsv_report` / "GSV" identifiers survive the rename (comments/function name only). Fix: correct the contract doc; optionally rename the internal function.

**8. [LOW · branding] Collapsed pin-only sidebar mark (D6.2) not implemented** — there is no sidebar collapse feature at all (fixed `w-60`). Either implement collapse+pin mark or descope explicitly.

**9. [LOW · branding] Export/PDF headers not brand-stamped (D6.4).** WO defers this ("later"); flagged so it isn't lost.

**10. [LOW · schema hygiene] `schema.sql` under-names single-column CHECKs relative to the models** (models use `chk_*`; schema.sql leaves most inline/unnamed), so a fresh DB built from schema.sql carries PG auto-generated constraint names — divergent from a DB built via migrations. Plus a **duplicate-CHECK risk** on `products.local_status`/`fridges.local_status`/`weekly_financials.fridge_count` if schema.sql is applied and then 0006/0007 re-add the same logic as named checks. Fix: name the CHECKs in schema.sql and guard the migrations against schema.sql's inline versions.

**11. [LOW · perf] Frontend JS bundle 629 kB (> 500 kB) with no code-splitting.** Cosmetic build warning; consider route-level `import()` if load time matters.

---

## 5. Cleanup Performed

All synthetic artifacts created during validation were removed; production state restored:

- Synthetic product `ZZTEST-VALIDATOR` — **deleted** (API 204). `ZZTEST%` count now **0**.
- Temporary `fridge_delivery_config` row (fridge 1 / weekday 1) — **deleted**. Config row count back to **0** (original empty state).
- Synthetic 2027-W3 pipeline rows — **deleted**: 1 dispatch (+lines), 1 weekly_menu (+lines), 2 forecast_runs (+results).
- **Stock**: never modified — `stock_movements` held at **8** for the entire pass; `v_stock_balances` unchanged. No compensating adjustment was necessary.
