# FrigoLoco ERP - Database Layer

PostgreSQL 16 schema for the FrigoLoco cloud ERP (smart-fridge catering ops).
Replaces the two Excel workbooks, three template files, 26 Office Scripts and
4 Power Automate flows described in spec
`specs/0001-frigoloco-excel-to-cloud-erp_2026-07-02_0810PM_UTC`.

Deliverable: pure SQL DDL (`schema.sql`), applied by
`backend/scripts/apply_schema.py` together with the numbered plain-SQL
migrations in `backend/scripts/migrations/`. **There is no Alembic in this
project and none is to be added** - schema changes are plain SQL scripts kept
under version control.

## ER overview - five aggregates

| Aggregate | Tables |
|---|---|
| **Catalogue** | `suppliers`, `categories`, `products`, `fridge_product_prices` |
| **Clients & fridges** | `clients`, `fridges`, `fridge_delivery_config`, `client_fees`, `client_service_charges`, `client_interventions`, `product_targets`, `menu_product_caps` |
| **Supply (warehouse stock)** | `purchase_orders`, `purchase_order_lines`, `order_no_counters`, `stock_movements` (+ `v_stock_balances` view) |
| **Dispatch & planning** | `weekly_menus`, `menu_products`, `menu_lines`, `forecast_runs`, `forecast_results`, `product_scores`, `fridge_product_scores`, `dispatches`, `dispatch_lines`, `restock_verifications`, `restock_verification_lines` |
| **Events & platform** | `sales_events`, `restock_events` (both month-partitioned), `product_reviews`, `weekly_financials`, `settings`, `alerts`, `audit_log`, `users` |
| **Fridge live stock** | `fridge_stock` - latest in-fridge units per (fridge, product), from Husky `/stock/current` |
| **Sync bookkeeping** | `sync_run` - one row per sync/snapshot run (window, status, counts, blob path, error) |

`sync_run` and `fridge_stock` are the **only** bookkeeping tables. There is no
`job_runs`, no `sync_cursors`, no `backfill_checkpoints`, no `generated_documents`,
no `reconciliation_daily`, and no `v_below_target` view.

`schema.sql` declares 36 tables; `sync_run` is created alongside them by
`apply_schema.py` via SQLAlchemy `create_all`. Enum columns are **TEXT + CHECK**,
not native PG enums (migration `0003_enums_to_text.sql`).

**Two different stock concepts live in this schema - do not conflate them:**

| | Warehouse stock | Fridge live stock |
|---|---|---|
| Table | `stock_movements` → `v_stock_balances` (a **view**) | `fridge_stock` (**stored**) |
| Grain | per product (**no fridge dimension**) | per (fridge, product) |
| Source | our own ledger writes (PO receipts, dispatches, adjustments) | Husky `GET /stock/current`, every 15 min |
| Derived or stored | always **derived**, never stored | **stored**, latest-only, no history |
| Read by | the Stock page (`GET /stock/balances`) | `menu_allocation_service` only - no API, no frontend |

## How to run

```bash
createdb frigoloco
psql -d frigoloco -f schema.sql
```

The file is idempotent-ish: enums are wrapped in duplicate-safe blocks, tables
and indexes use `IF NOT EXISTS`, functions use `CREATE OR REPLACE`, seed
inserts use `ON CONFLICT DO NOTHING`. Re-running it against an existing
database is safe. For a from-scratch rebuild:

```sql
DROP SCHEMA public CASCADE; CREATE SCHEMA public;
```

then re-apply the file.

## Warehouse stock: ledger semantics (slide 24 - non-negotiable)

This section is about **warehouse** stock only - what is on our own shelves, per
product, with no fridge dimension. For what is physically inside a fridge, see
*Fridge live stock* below.

`stock_movements` is an **append-only signed ledger**; warehouse balance is
`SUM(qty)` per product.

- **Non-negativity is enforced in the database**: a `BEFORE INSERT` trigger
  takes a per-product transaction-scoped advisory lock, computes the running
  balance, and raises (`ERRCODE check_violation`) if the insert would go below
  zero. The API layer maps this to HTTP 409 + a `negative_blocked` alert.
- **Append-only**: a second trigger rejects any `UPDATE`/`DELETE`. Corrections
  are compensating movements, never edits.
- **Sign conventions** (CHECK-enforced): `po_receipt` > 0, `dispatch` < 0,
  `cancellation_reversal` < 0 (cancelling a *received* PO explicitly removes
  the stock - fixes the Excel cancel bug), `adjustment` either sign but always
  with a non-empty `reason`.
- **`v_stock_balances`** restates the Excel *Stock & Ordered* rule (R6) for
  the ledger design:
  - `physical_qty` = `SUM(stock_movements.qty)` - what is in the warehouse
  - `on_order_qty` = `SUM(GREATEST(qty_ordered − qty_received, 0))` over lines
    of **pending** POs only (received/cancelled POs contribute nothing)
  - `available_qty` = `on_order_qty + physical_qty` - the Excel "available"

## Fridge live stock (`fridge_stock`)

Separate model, separate table: **what is inside each fridge right now**, stored
per `(fridge_id, product_code)` (that pair is the PRIMARY KEY) and sourced from
Husky `GET /stock/current`. This is the only source of fridge-level stock.

- **Latest-only, mark-and-sweep.** The `snapshot_stock` job (every 15 min)
  upserts every row of the newest `/stock/current` payload under a single
  run-wide `taken_at`, then, in the same transaction, DELETEs every row that run
  did not touch. The table therefore mirrors exactly what the vendor last
  reported: a fridge or product that disappears from the feed disappears from
  the table. A missing row means "not in that fridge right now" (live = 0).
  Replaces the append-only `stock_snapshots` log
  (`backend/scripts/migrations/0009_fridge_stock_latest_only.sql`).
- **Guard:** an **empty** vendor payload never triggers the sweep - an empty
  response means a vendor problem, not "all fridges are empty".
- **No history, and no consumer for one.** Only the newest reading per
  (fridge, product) was ever queried, so history is not retained. This is
  settled: there is no retention or downsampling question to re-open, because
  there is no reader to serve.
- **Exactly one reader:** `backend/app/services/menu_allocation_service.py`,
  which computes the snacks/drinks branch `restock = max(target_qty - live, 0)`.
  There is **no API endpoint and no frontend** that reads fridge stock, and
  nothing reconciles it against warehouse stock.
- **Staleness guard (implemented):** all rows share one `taken_at` generation.
  If the newest `taken_at` is older than `STOCK_READING_MAX_AGE` (2 hours) or
  absent, allocation still runs on last-known units, but every
  `target_replenish` line is flagged `stock_stale` and a warning is logged. The
  guard lives in the allocation reader - not in a cron job, not as an alert, not
  on a health endpoint.

## Order numbering (R4)

`next_order_no()` returns `YYYY-NNNNN` from the `order_no_counters` per-year
counter table. The `INSERT … ON CONFLICT DO UPDATE … RETURNING` upsert
row-locks the year's counter row until commit, so concurrent PO creation can
never draw duplicate numbers (rolled-back transactions leave gaps, which is
acceptable).

## Partitioning maintenance

`sales_events` (by `sold_at`) and `restock_events` (by `occurred_at`) are
`PARTITION BY RANGE` with **one partition per month**. Partitions for
**2025-01 through 2027-01** are pre-created by the schema (50 child tables).

- `create_event_partitions_for_month(date)` - creates both tables' partitions
  for the month containing the given date (idempotent).
- `create_next_month_event_partitions()` - ensures current + next month exist.
  This runs in the **cron container**, not the backend:
  `cron/cron/jobs/partition_maintenance.py`, registered on the APScheduler
  worker (`cron/cron/scheduler.py`) monthly on the 1st at 01:00 Europe/Brussels.
  An insert for a month with no partition **fails**, so keep this job alive or
  pre-create further years.
- Unique keys on partitioned tables must include the partition key, so the
  sync's idempotent upsert conflicts on `(husky_ref, sold_at)` /
  `(husky_ref, occurred_at)`.

## Excel artifact → table map

| Excel artifact | Table(s) |
|---|---|
| SupplierInfoTable | `suppliers` |
| Hardcoded category lists in scripts | `categories` (seeded, with R8 dispatch print order) |
| producttype API cache + Menu headers | `products` |
| Forecast V2 cols C–E | `fridge_delivery_config` |
| Snacks & Drinks Target Map (3,522 rows) | `product_targets` |
| OrdersSummaryTable / OrdersLineItemsTable | `purchase_orders`, `purchase_order_lines` |
| StockAndOrderedTable recompute | `stock_movements` + `v_stock_balances` |
| Menu sheet weekly tabs | `weekly_menus`, `menu_products` |
| Update Forecast runs / Forecast V2 output | `forecast_runs`, `forecast_results` |
| Product Rating scorecard | `product_scores` (+ `fridge_product_scores`, new dual model) |
| Global Dispatch History (20,692 rows + backup sheet) | `dispatches`, `dispatch_lines` |
| Husky purchases / restock / productreview pulls | `sales_events`, `restock_events`, `product_reviews` |
| RestockVerificationTemplate.xlsx | `restock_verifications`, `restock_verification_lines` |
| Weekly View manual inputs + WeeklySummaryDataTable | `weekly_financials` |
| Fee List / Service Additionals | `client_fees`, `client_service_charges` |
| Tunable cells in both workbooks | `settings` (seeded: scoring weights 0.62/0.05/0.33, per-category forecast margins 0, POS fee 9 %, RFID fee €0.10). The seeded `expiry_alert_days` row is **dead config**: no expiry-alert job exists to read it. |
| PA alert emails | `alerts` - **only partially**. See below. |

> **The Power Automate alert emails are NOT yet replaced.** `alerts.alert_type`
> permits `expiry`, `low_stock`, `below_target`, `negative_blocked` and
> `rfid_offline`, but **only `negative_blocked` is ever written** (by
> `dispatch_service` when the non-negativity trigger rejects a dispatch). Every
> other alert class is **NOT BUILT**: nothing produces the rows, no job scans
> for them, and there is no email or digest path off the table. The
> `COMMENT ON TABLE alerts` in `schema.sql` describes the intended end state,
> not current behaviour.
| - (new: slides 13/14/23) | `users`, `clients`, `client_interventions`, `fridge_product_prices`, `menu_product_caps`, `audit_log` |

Every table also carries a `COMMENT ON TABLE` in the schema saying what it
replaces.

## Migration sources (one-time import - Phase 1.7)

- **`Excel Files/Forecasting Tool/Smart Fridge Forecasting Tool V5.xlsx`**:
  suppliers, delivery configs, targets, order history (517 orders / 2,588
  lines), dispatch history (20,692 lines), settings cells.
- **`Excel Files/Forecasting Tool/Weekly & Monthly Return V2.xlsx`** - weekly
  financials (30 weeks), fee list, fraction list, service additionals.
- **`Excel Files/templates/DispatchTemplate.xlsx`** (42 sheets) + Husky
  facility API - fridges/clients, delivery addresses & instructions.
- **Husky RFID API backfill** - 12+ months of `purchases`, `restock`,
  `productreview` into the event tables (idempotent upsert on `husky_ref`);
  product catalogue from `producttype`. Normalize at ingestion: comma-decimal
  buy prices, tag statuses, and both
  `friendlyName` / `fridge.name` join keys → `fridges.husky_id`. Money is
  **not** converted: vendor `int64` minor units are stored RAW as `BIGINT`
  cents (no ÷100 at the sync boundary).
- Known exceptions to carry into the migration report: 218 products missing
  `shelf_life_days` (column is nullable), ~20 "Box n°" test products to
  exclude, per-fridge price mapping to confirm with ops.

## Verification status

`schema.sql` was applied end-to-end against a scratch PostgreSQL 18.3 database
(`frigoloco_schema_check`, since dropped): clean apply, clean idempotent
re-run, and behavioral tests passed for the non-negativity trigger, the
append-only triggers, the adjustment-reason CHECK, `next_order_no()`
sequencing, partition routing, and `v_stock_balances` math. Target runtime is
PostgreSQL 16; no PG17/18-only features are used.
