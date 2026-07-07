# Work Order — Week/Day Workflow Rework, Enum Removal, Partitioned Dispatch, Reports

> Captured verbatim from Ismail's requirements (2026-07-03, with Excel screenshots of Order View, Dispatch View, Menu, Forecast V2, Product Rating). Orchestrated by the verifier session; implemented by delegated agents. Goals: functional · aesthetic · flexible · maintainable · scalable.

## D1 — Model-layer decisions (backend-models agent)

1. **No PG enum binding.** Replace `pg_enum()` / `SAEnum(native_enum=True)` with `native_enum=False` everywhere (VARCHAR + CHECK). Migration `0003_enums_to_text.sql` (plain SQL): every enum-typed column → `text` with a CHECK constraint listing the values; drop the now-unused PG enum types. Idempotent guards.
2. **`dispatch_lines` becomes a partitioned table** (largest projected table): RANGE partition, monthly, on the dispatch delivery date (denormalise `delivery_date` onto lines for the partition key; composite PK includes it — mirror the `sales_events` pattern). Recreate via migration (near-empty today), pre-create 2025–2027 partitions, and make the partition-maintenance duty explicit.
3. **Full pass over every model**: verify each column's datatype and CHECK against schema.sql and the money-in-cents migration (bigint cents everywhere money); add missing CHECKs (qty >= 0 where sensible, week 1–53, weekday 1–7, fractions in [0,1)); named constraints; update schema.sql to stay the single DDL source.

## D2 — Workflow semantics (backend-workflow agent)

**Everything keys on (iso_year, week_no, day_name).** Forecast → Menu → Dispatch is a pipeline; each stage can (a) import from the previous stage, (b) save, (c) load its own previously saved data, (d) overwrite with explicit confirmation.

- **Forecast**: `POST /forecasts/run` computes (does NOT auto-save); `POST /forecasts/save` persists keyed (year, week, day_name) — if a saved forecast exists for that key → `409 {code: "exists", details}` unless `overwrite=true`, which deletes prior rows + reinserts atomically. `GET /forecasts/saved?year&week&day_name` = import-from-database. Forecast config: `model` selector — only `"moving_average_3w"` today, enum-style string, designed for future models (params JSONB per run).
- **Menu**: same key + same overwrite semantics. `POST /menus/import-from-forecast?year&week&day_name` seeds a draft menu from the saved forecast (quantities per fridge×category allocated by product score). User edits (add products, add fridges, change qty) then `POST /menus/save` (overwrite-confirm on existing key). `GET /menus/saved?year&week&day_name` = load previous.
- **Dispatch**: same key + same semantics. Import-from-menu, save (= PLANNED, does NOT touch stock), load-saved, overwrite-confirm. **"Create individual dispatch" = actual dispatch**: flips `is_dispatched`, snapshots prices, writes negative stock movements (only here!), and later generates templates/emails (doc generation still out of txn scope).
- **Orders**: pull per-supplier product quantities from the saved menu (`POST /purchase-orders/draft-from-menu?year&week&day_name&supplier_id`) — mirror of the Excel "Order details (va chercher dans le menu)" button.
- **Stock**: derived only — verify no save-time deduction path exists; add explicit **opening-stock** manual adjustment flow (reason-required, e.g. initial stock take).

## D3 — Reports (backend-reports agent)

- Rename GSV → **Fridge Report**: `GET /finance/fridge-report` returns per-product rows (name, code, category, added qty, unit buying price, unit selling price) + summary (total added qty, food cost, revenue, food margin).
- **Excel export**: `GET /finance/fridge-report/export.xlsx` — **Polars** `write_excel` for the table body, **openpyxl** to place the summary block at the TOP (summary first, table below it).
- **Product rating scorecard**: enrich `GET /forecasts/scores` to return the full Excel-equivalent columns: product name/code/category/brand, shelf life, buying price, sold price, VAT, profit margin, total sold qty, total added qty, %sold, positive/negative review counts, %positive, final score. All raw facts already in DB; expose them.
- Supplier info (name, order emails, warehouse address) — confirmed already implemented (schema + CRUD + UI); verify email + warehouse fields round-trip in the UI.

## D4 — Frontend rework (fe-workflow + fe-reports agents)

- **Week/day selectors** on Forecast, Menu, Dispatch pages + buttons mirroring the Excel workflow: Import from Forecast / Import from Menu / Import from Saved / Save (with overwrite-confirm dialog) / Create Individual Dispatch.
- **Menu grid like the Excel sheet** (screenshot): category header band → supplier row → product columns → detail rows (code, purchase price, sales price, VAT%, margin, score, shelf life, stock&ordered, total qty) → fridge rows × qty cells. Horizontal scroll, sticky first column. **Cascading pickers**: category → supplier → product; filtering done CLIENT-SIDE over the full catalogue (~600 products — load once, filter locally; no per-change API calls).
- **Configurable columns-per-category** (Settings): minimum column slots per category for Menu/Dispatch grids; imports exceeding the configured count are allowed (config is a minimum, not a cap).
- **Forecast page like Forecast V2**: client (fridge) rows, min qty, days-to-fill, per-category forecast cells, %adjust row; side block of actuals per category (Added, Sold, Added/Sold% with the red/yellow/green thresholds); date-range display; model selector dropdown (single option today).
- **Fridge Report page**: start/end/fridge pickers, table + summary tiles, Export to Excel button (downloads the backend export).
- **Product Rating page**: full scorecard table (all columns above), weights display, Update Rating (recompute) button.
- Aesthetic bar: match the existing app design system; loading/empty/error states; horizontal-scroll containers must not scroll the page body.

## D5 — Husky master-data sync: ownership contract + UI sync button (added 2026-07-03)

User requirement: fridge + product data auto-syncs from Husky AND is user-triggerable from the UI; local-only fields and manual status markings must survive every sync; checkpoints/process visible.

1. **Field-ownership contract (per table, documented in code):**
   - *Husky-owned* (overwritten on every sync): product name, code, category, brand/supplier link, prices, VAT, expiryDays, image; fridge husky_name/friendly_name/serial/status/facility link; per-fridge prices.
   - *Local-owned* (NEVER touched by sync): min_qty, default_fill_days, delivery config, targets, caps, fees, notes, display_order, is_test — and the **manual status override**.
   - **Manual status override**: add `local_status text NULL CHECK (local_status IN ('inactive','cancelled'))` to `products` (and `fridges`): NULL = follow Husky (present→active, absent→inactive); a non-NULL value is user-forced and WINS over sync. Effective activity = local override if set, else Husky-derived. Sync must upsert with an explicit column list (husky-owned only) — never blanket-update.
2. **Sync relocation for reuse (fixes criticizer S2-6 properly):** move the sync/transform logic from `cron/cron/jobs/*` into `backend/app/husky/sync.py` (importable domain functions); cron jobs become thin CLI/scheduler wrappers calling them. No backend→cron import (cycle).
3. **Sync API:** `POST /api/v1/sync/husky/{feed}` (feed ∈ catalogue | fridges | prices | all) — runs the sync, returns the `sync_run` row; `GET /api/v1/sync/runs?endpoint&limit` — checkpoint history (status, window, counts, started/finished). Long-running feeds may use FastAPI BackgroundTasks with the sync_run row as the progress handle.
4. **Frontend:** "Sync from Husky" button + last-sync stamp (from sync_run) on Products and Fridges master pages; toast on completion with counts; status dropdown on product/fridge rows exposing the manual override (Active [follow Husky] / Inactive / Cancelled) with a caption explaining sync-override semantics; a small Sync page/section (under Settings or Masters) listing recent sync_run checkpoints.
5. **Frontend validation (standing requirement):** after every frontend wave, re-verify: `npm run build` clean, all routes 200, each changed page exercised against the live API, grid horizontal scroll contained.

## D6 — FrigoLoco branding (added 2026-07-03, logo provided by Ismail)

Brand: teal field, white Didone-serif wordmark "Frigo Loco" with a location-pin dotting the "i", tagline "LOCAL · HEALTHY · HUMAN". Sampled brand teal ≈ `#45BCB4` (fine-tune from the real asset).

1. Adopt brand teal as the app primary: `--series-1`/`--primary` → brand teal (light: `#2fa39b`-ish for AA contrast on white, dark: `#45BCB4`); sidebar becomes brand teal or keeps dark navy with the teal as accent — pick whichever keeps WCAG AA and matches the logo mood, document the choice.
2. Sidebar brand block: `frontend/public/frigoloco-logo.svg` (placeholder wordmark committed — replace with the official file when Ismail drops it in, keep the same path) + collapsed-state pin-only mark.
3. Favicon: location-pin mark on brand teal (update `public/favicon.svg`).
4. Login/empty states + PDF/export headers later inherit the same brand block.
5. ASK ISMAIL: drop the original logo file (PNG or SVG) into `frontend/public/` to replace the placeholder.

## Sequencing

cents-migration (running) → D1 models agent → D2 + D3 (parallel) → D4 (parallel, 2 agents) → critic+QA verification pass → fixes. Verifier (main session) checks each hand-off; nothing merges unverified.
