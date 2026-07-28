# Autonomous Work Checkpoint

Running log of everything I (Claude) implement, assume, and decide while the user
is away. The user reviews this at the end. Newest entries at the top of each section.

Started: 2026-07-28. Model: Opus 4.8.

## How to read this
- **DECISION** = a design/behaviour choice I made without being able to ask. Please confirm.
- **ASSUMPTION** = something I inferred from code/spec/Excel; correct me if wrong.
- **DONE** = implemented + validated (tests/browser). Commit hash noted where pushed.
- **OPEN** = known gap / follow-up I did not do (with why).

## Scope the user gave me (2026-07-28)
1. Category-scoped Menu/Dispatch: in the legacy Excel you could pull/save Menu (and
   Dispatch) for ONE category only, or for ALL categories. Add that. Test, commit, push.
2. Drive Purchase Order modifications too (warehouse-first PO redesign per slide 9).
3. Read `FrigoLoco_Dev_Presentation_V5_Final.pptx`, find ALL missing features vs the
   current app, implement them via subagents (I act as validator), commit + push +
   validate, logging assumptions/decisions here.
- cmux remote-control socket is NOT enabled, so I cannot reach the user's other two
  Claude sessions. Coordinating via git + this doc instead.

---

## Workstream 1 - Category-scoped Menu/Dispatch save & pull

### API contract (DECISION)
Scoping is controlled by an optional `category_id`:
- **Menu** `POST /api/v1/menus/import-from-forecast?...&category_id=<id>` - preview only
  that category's allocation (omit -> all categories, unchanged).
- **Menu** `POST /api/v1/menus/save` body gains `category_id?: int`. When set, only that
  category's `menu_lines` are replaced; other categories' saved lines are untouched.
  The overwrite-confirm 409 `{code:"exists"}` fires only if THAT category already has
  saved lines. `category_id=null` keeps the whole-menu behaviour.
- **Dispatch** `POST /api/v1/dispatches/import-from-menu?...&category_id=<id>` - preview
  filtered to that category.
- **Dispatch** `POST /api/v1/dispatches/save` body gains `category_id?: int`, same
  category-scoped replace + category-aware `exists` check. `_replace_lines` already
  supported `category_id`; save_planned now threads it through.
- Backend validates that every line in a category-scoped save actually belongs to that
  category (422 otherwise), so a client can't smuggle other categories in.

### Frontend (DECISION)
- Menu + Dispatch toolbars get a category `<Select>`: "All categories" (default) or one
  category. "From Forecast"/"From Menu" and "Save" respect the selection.
- Scoped import MERGES into the current grid (keeps other categories) instead of
  replacing it; scoped save sends only the selected category's lines.
- New shared component `frontend/src/pages/ops/components/CategoryScopeSelect.tsx`
  ("All categories" + each category in display order). New grid-state method
  `mergeCategoryFromGrid` + `categoryProductIds` in `grid.ts`.

Status: DONE. Validated: 7/7 backend workflow tests pass (incl. 2 new scope tests
`test_category_scoped_menu_save`, `test_category_scoped_dispatch_save_and_import`);
frontend `tsc -b` clean; browser confirms the selector renders on Menu (lists all
10 categories) and Dispatch. Committed + pushed (see git log). NOT browser-round-
tripped to avoid mutating the user's working date (2026-W31-Tuesday) - backend
tests already prove other categories are preserved on a scoped save.
ASSUMPTION: the category options are the full reference category list (from
GET /categories), not only categories currently on the grid - so you can pull a
category that isn't yet present. Tell me if you want it limited to on-grid ones.

---

## Workstream 2 - Purchase Order modifications
Status: PENDING audit (slide 9 = view-by-date, stock page, in-stock vs on-order,
warehouse receiving view, scan & attach delivery note, later Peppol link).

## Concurrency hazard (IMPORTANT - read before reviewing my commits)
Another Claude session is editing this same working tree right now. As of this run it
has UNCOMMITTED changes to: `frontend/src/pages/supply/PurchaseOrdersPage.tsx`,
`StockPage.tsx`, `supply/types.ts`, `finance/FinancePage.tsx`, `masters/ProductsPage.tsx`,
`masters/SyncPage.tsx`, `backend/app/models/operations.py` (week_start column),
`architecture/database/schema.sql`, and several backend test files.

DECISION: I will NOT touch those files - editing them would clobber the other session's
work. So I am NOT running a broad parallel "swarm" that writes across the whole tree
(that would corrupt their uncommitted work and produce merge chaos). Instead I sequence
self-contained slices in files the other session is NOT touching, delegate each slice's
implementation to a subagent (orchestrator pattern), validate, and commit per slice.
If you want the full parallel swarm, either close the other sessions or enable the cmux
socket so I can coordinate with them.

Because the other session is already deep in the **Purchase Orders / Stock frontend**,
Workstream 2 (PO modifications) is best DRIVEN by giving that session the backend API it
needs, not by me editing its open files. The PO backend gaps + guidance are in the
register below; I will implement PO BACKEND pieces (untouched files) where safe and leave
the PO frontend to the session that owns it.

## Workstream 3 - Feature Gap Register (deck vs current app)
Source: `FrigoLoco_Dev_Presentation_V5_Final.pptx` (24 slides) diffed against three
codebase audits (backend, frontend, PO/Stock). Legend: [OK]=present, [~]=partial,
[X]=absent. Priority P1 (core, well-scoped) -> P3 (large / needs product decision).

### Already done well (no action)
- [OK] Stock: manual adjust w/ reason, audit trail, CHECK(stock>=0), negative-block alert.
- [OK] PO: receive flow (over-receipt ack), cancel-with-stock-reversal, on-order vs
  in-warehouse vs available (v_stock_balances), draft-from-menu / draft-from-dispatch.
- [OK] Menu: per-fridge caps, product targets, stock-aware allocation (live fridge stock).
- [OK] Dispatch: past-date force safeguard, add-products-manually, category display order.
- [OK] Forecast: sell-through % + colour codes (UI), holiday exclusion (low-sales heuristic).
- [OK] Clients: info, fees, intervention log. Finance: weekly + monthly P&L, fridge xlsx.
- [OK] Category-scoped Menu/Dispatch save+pull (Workstream 1, this run).

### P1 - quick, self-contained, high value
1. [X] **Dispatch: clone/copy a dispatch day** to another date (slide 10 "Clone dispatch
   day"). Backend: copy saved dispatch lines key->key. Files: dispatch_service/dispatches
   router (I own these) + DispatchPage (I own). SAFE. -> implementing this run.
2. [~] **PO: view/filter by delivery date** (slide 9). Backend: add `delivery_from/
   delivery_to` (+ maybe `due=this-week/overdue`) to GET /purchase-orders. Files:
   purchase_orders router + orders_service + schemas/orders (currently untouched). The
   frontend date filter belongs to the session owning PurchaseOrdersPage. -> BACKEND only,
   this run, to guide the PO work.
3. [X] **Alerts actually raised: low-stock + expiry** (slide 12). Only `negative_blocked`
   is ever constructed. Add a cron/service that raises `low_stock` (per-product min
   threshold) and `expiry` (DLC within N days) alerts. Files: cron/ + a small service
   (untouched). Needs a threshold source (settings + per-product). -> P1 backend.
4. [~] **Dispatch: withdrawal list** (slides 5,10) - products whose DLC is too short to
   cover the delivery window, flagged for the driver to pull. Needs fridge live stock +
   product shelf_life + coverage window (days_to_fill). Medium; forecast/dispatch service.

### P2 - medium, mostly backend, some product nuance
5. [X] **Menu: exclude-product-from-fridge** (slide 8). New table (fridge_id, product_id)
   + allocation/menu filter. Files: models + menu_allocation_service + a router.
6. [X] **Forecast: residual fridge-stock deduction (DLC-based)** (slide 5). Net to deliver
   = max(0, forecast - deductible residual stock where DLC>=window). Forecast engine change.
7. [X] **Scoring: dual global x per-fridge (50/50)** (slides 4,18). `fridge_product_scores`
   table EXISTS but is never written/read. Implement per-fridge score + 50/50 combine.
8. [X] **New-product baseline (<=250 sales)** (slides 8,18): use avg global score as
   placeholder until real data. Scoring service.
9. [X] **PO: scan & attach delivery note** (slide 9). Needs blob storage + multipart
   upload endpoint + attachment column/table + UI. finance.py has an UploadFile pattern.
10. [~] **Dispatch column totals vs warehouse stock (red if exceeded)** + per-row food
    cost / revenue (slide 20). PlanningGrid enhancement (I own that component).

### P3 - large / needs your decision before I build
11. [X] **Auth + roles/access control** (slide 14). User table + UserRole enum exist but
    NO login/JWT/guards. Big, security-sensitive - I will NOT build this blindly.
12. [X] **Logistics / routing / driver app** (slide 11) - route optimisation, pick lists,
    driver mobile view, SMS. Large new domain.
13. [X] **Add-on services pages: coffee / fruits / business lunch** (slide 7) - auto-dispatch
    schedules. New domain; only a generic client_service_charges exists today.
14. [X] **Weather adjustment** (slide 4) - needs 18 mo weather/sales correlation + a weather
    source. Large, data-dependent.
15. [X] **Returns flow** (slides 14,15) and **PDF export** (deck shows delivery sheets;
    app only exports xlsx). **2-dispatch-per-day** (slide 10). **Fridge groups** (slide 8).

### Assumptions logged
- ASSUMPTION: "Clone dispatch day" copies the SAVED (planned) lines of the source day into
  a NEW planned dispatch on the target date, status=saved, no stock effect (stock only
  moves on create-individual). Overwrite-confirm if the target already has a saved dispatch.
- ASSUMPTION: PO date filter uses `expected_delivery_date` (the warehouse-relevant date),
  not order_date.

Status: register COMPLETE. Implementing P1 items in untouched files, one at a time.

### Implemented this run (after the register)
- **P1 #1 Clone dispatch day** - DONE. Backend `POST /api/v1/dispatches/clone`
  (`dispatch_service.clone_dispatch`): copies a saved source day's planned lines onto a
  target day as status=saved, NO stock effect; overwrite-confirm on the target; 404 if
  the source has no saved dispatch; 422 if source==target. Frontend: "Clone day" button
  + target-day modal + overwrite confirm on DispatchPage (a file I own). Test:
  `test_clone_dispatch_day`. Validated in browser (modal opens, picker works).
- **P1 #2 PO filter by delivery date (BACKEND)** - DONE. `GET /api/v1/purchase-orders`
  now accepts `delivery_from` / `delivery_to` (filters `expected_delivery_date`). Files:
  purchase_orders router + orders_service (both untouched by the other session). Test:
  `test_po_delivery_date_filter`. The PO frontend date-filter control is intentionally
  LEFT to the session that owns PurchaseOrdersPage.tsx - this backend just enables it.
  GUIDANCE for that session: pass `delivery_from`/`delivery_to` (ISO dates) to the
  existing GET; add a "due this week / overdue" quick filter keyed on those params.

- **P2 #8 New-product baseline score (<=250 sales)** - DONE (backend). In
  `scoring_service.recompute_scores`: after computing every product's score, products
  whose window sales are at/under the threshold inherit the AVERAGE score of established
  products (sales above the threshold) as a placeholder, so sparse data can't skew their
  rank. Threshold is `new_product_sales_threshold` setting (default 250). Pure helper
  `_average_established_score` unit-tested in `tests/test_scoring_baseline.py` (3 tests).
  ASSUMPTIONS: (a) "sales" = count of non-refunded sales_events in the 365-day window;
  (b) threshold is strict (sales == 250 counts as NEW); (c) when no product clears the
  threshold, NO baseline is applied (everyone keeps their computed score); (d) new
  products keep their raw pct_sold/margin/review components stored - only final_score is
  replaced (there is no is_baseline column to flag it). The per-fridge half of the
  dual-scoring model (slide 18, `fridge_product_scores` table) is still OPEN (P2 #7).

### Backups still OPEN (need your go-ahead or the other session's coordination)
- P1 #3 low-stock/expiry alerts, all P3 (see register).
  I am pausing broad implementation because the other session is mid-flight across
  PO/Stock/finance and a parallel swarm would collide. Tell me which to pick up next, or
  enable cmux so I can coordinate.

## Workstream 5 - Residual fridge-stock forecast deduction (slide 5) - REVISED

CORRECTION to the earlier "blocked on DLC data" note: it is NOT fully blocked. The Husky
`/stock/current` payload carries a REAL per-unit expiry date (`CurrentTag.expiryDate`, one
per RFID tag) and our parser already reads it (`app/husky/schemas.py` `StockTag.expiryDate`).
The snapshot job just discards it - `app/husky/sync.py snapshot_stock` collapses the tag
list to `len(...)` and `fridge_stock` (models/sync.py) has no expiry column. So exact
per-unit expiry is ONE capture change away. Three fidelity tiers:
- Tier 1 (correct): persist `CurrentTag.expiryDate` per unit, then residual = units whose
  expiry >= next-delivery date. Needs: fridge_stock expiry column (migration + model) +
  snapshot job change + forecast read. Also unlocks the withdrawal list for free.
- Tier 2: product-level `shelf_life_days` (max life, ~218 null) - a coarse proxy.
- Tier 3: reconstruct unit age from `restock_events` added-dates - imperfect tag matching.

DECISION: implement Tier 1 (it is the only operationally safe version - Tier 2/3 over-deduct
and risk stockouts). Forecast insertion point: `forecast_service._compute_cells`, right
after `forecast_qty` is computed, subtract the per-(fridge,category) residual and clamp >=0;
feed it a residual map precomputed in `_compute_run` (mirrors `_daily_category_units`).
Coverage-window end = delivery_date + that fridge/weekday `days_to_fill`.

Status: DONE (backend, Tier 1). Shipped:
- `fridge_stock.expiry_dates TIMESTAMPTZ[]` column (model `models/sync.py` + migration
  `0012_fridge_stock_expiry.sql`).
- `snapshot_stock` now captures each tag's `expiryDate` (was discarded). Robust via
  `getattr` so a bare-id tag can't crash the job.
- `forecast_service`: `_residual_by_key` counts in-fridge units whose expiry is on/after
  the next-delivery date per (fridge, category); `_compute_cells` subtracts it and clamps
  >=0. `params.residual_deduction=true` records that it ran.
- Tests: `test_forecast_residual_stock_deduction` (2 good + 1 expiring -> deducts 2) and
  `test_forecast_residual_never_goes_negative` (clamp). Full workflow suite 11/11, husky
  snapshot 3/3 green.
ASSUMPTIONS: (a) a unit is "good" if its captured expiry >= the next-delivery date; units
expiring sooner are NOT deducted (they belong on the withdrawal list); (b) units with no
captured expiry are NOT deducted (conservative - never over-deduct / risk a stockout);
(c) NO staleness guard in the forecast reader yet (menu allocation already guards stock
staleness on the operationally-critical path); (d) `days_to_fill` is the coverage window.
FOLLOW-UPS now unblocked: the **withdrawal list** (units expiring BEFORE the window) is
the same data, one query away.

### Withdrawal list (slides 5, 10) - DONE (backend)
`GET /api/v1/dispatches/withdrawal-list?year&week&day_name` -> per (fridge, product) the
count of in-fridge units expiring BEFORE the coverage window end (the exact complement of
the residual deduction), for the driver to pull. `dispatch_service.withdrawal_list` +
`WithdrawalListOut` schema. Test `test_dispatch_withdrawal_list`. The frontend surface (a
withdrawal panel on the Dispatch sheet) is still TODO - the API is ready for it.

### !! ENVIRONMENT FINDING - please check
The `fridge_stock` TABLE DID NOT EXIST in the connected Railway DB (migration 0009 was
never applied here). Nothing had failed because no test/endpoint exercised it, but the
menu-allocation snacks/drinks branch (its only reader) WOULD fail against this DB. I
created the table from the ORM model (idempotent `create(checkfirst=True)`), now including
the new `expiry_dates` column, and added migration 0012. `architecture/database/schema.sql`
is held by the other session, so I did NOT edit it - it still needs the `expiry_dates`
column added there for parity (and 0009's fridge_stock may need reconciling in this DB).

## Workstream 6 - Recurring provisioning + per-fridge product choices (DESIGN, tracked)

### A. Recurring product provisioning / add-on auto-dispatch (slide 7)
GOAL: products that recur on a schedule (5 kg fruit every Mon+Wed, coffee, business lunch)
auto-appear on the dispatch sheet, excluding holidays.
PROPOSED MODEL - new table `scheduled_provisions` (goes in `master.py`, currently free):
  id, fridge_id (FK; client-level services resolve to the client's fridge), product_id (FK),
  qty (int), service_type TEXT+CHECK (fruits|coffee|business_lunch|adhoc),
  recurrence: EITHER `weekdays INT[]` (ISO 1-7, recurring) OR `on_date DATE` (one-off, e.g.
  business lunch) - exactly one set; `exclude_holidays BOOL default true`;
  `po_reference TEXT null` (business lunch); `valid_from/valid_to DATE null`; `active BOOL`;
  created_at/updated_at.
INTEGRATION: a dispatch step "apply recurring" expands active provisions whose weekdays
contain the delivery weekday (or whose on_date == delivery_date), skipping holidays, into
dispatch lines with a new `LineSource.recurring` (enums.py + a CHECK-update migration; or
reuse `manual` to avoid the enum migration - TRADE-OFF logged). Merges into the matrix like
the category import.
API: CRUD `/api/v1/provisions`; dispatch integration endpoint. FRONTEND: an "Add-on services"
page.
OPEN QUESTIONS for you: (1) `exclude_holidays` needs a FORWARD holiday CALENDAR - none exists
(forecast infers holidays retrospectively from low sales). Add a small `holidays(date)` table
/ setting? (2) Target by fridge or by client? I propose fridge (dispatch is fridge x product);
client-level services resolve to the client's fridges. (3) qty for weight-based items
("5 kg") - store as integer amount with product unit semantics, or add a unit field?

### B. Per-fridge product choices / exclude-product-from-fridge (slide 8)
GOAL: the weekly menu is the global permitted list; per fridge you exclude specific products
(e.g. no sandwiches at location X), and per-fridge quantities/prices already exist
(product_targets, menu_product_caps, fridge_product_prices).
PROPOSED MODEL - new table `fridge_product_exclusions` (in `master.py`, alongside the other
per-(fridge,product) tables): (fridge_id FK, product_id FK) composite PK + created_at.
Presence = excluded. (Exclusion chosen over an allow-list: simpler, matches the deck's
"tick/untick to exclude"; the menu is already the base allow-list.)
INTEGRATION: menu import-from-forecast split skips excluded (fridge,product);
`menu_allocation_service` filters them out per fridge; the grid marks excluded cells disabled.
API: GET/PUT `/api/v1/menus/fridge-exclusions?fridge_id=...` mirroring the existing
product-targets / menu-caps endpoints in `menus.py`. FRONTEND: a per-fridge exclusion editor
(Fridges delivery-config-style dialog) or a tick in the grid.
NOTE: both A and B need NEW TABLES = schema changes. `schema.sql` is held by the other
session, so I will add via NEW migration files (numbered to avoid collision) + `master.py`
model + note that `schema.sql` needs a sync. B is the smaller/cleaner one to build first.
