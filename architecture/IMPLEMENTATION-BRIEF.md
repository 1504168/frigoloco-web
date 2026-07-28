# Implementation Brief - Canonical Decisions (Verifier-resolved)

> Produced 2026-07-03 by the verifier session from a full digest of specs 0002/0003/0004, `architecture/*`, and CLAUDE.md.
> The sources contain 19 documented contradictions (§E below). Implementers follow THIS sheet; deviations recorded here, not re-litigated.
> User-authorized basis: "keep grinding without asking and do fair assume" (2026-07-03).

## Canonical decisions (contradiction → resolution → why)

| # | Topic | Resolution | Why |
|---|---|---|---|
| 1 | Migrations | **No Alembic.** Plain SQL: `architecture/database/schema.sql` applied by `backend/scripts/apply_schema.py`; future changes = numbered SQL scripts | CLAUDE.md explicit decision (latest) |
| 2 | API surface | **`/api/v1` prefix + architecture/backend/README route names** (`/purchase-orders`, `/forecasts/run`, `/finance/weekly/{y}/{w}`, `/dispatches/{id}/...`) | schema.sql and mockups were built against that design |
| 3 | Scheduler | **APScheduler** worker (`python -m cron.scheduler`), own container, Europe/Brussels for operational jobs; every job also a CLI `python -m cron.jobs.<name>` | User decision 2026-07-03 |
| 4 | Weekly food-cost basis | **ADDED (restock) value** weekly; **DISPATCHED value** monthly-by-fridge | Verified against the actual workbook formulas (Fridge Food Cost = Added Food Cost column); spec 0003's dispatch-based weekly formula is wrong |
| 5 | Money | **BIGINT integer minor units (cents) in DB** (matches Husky int64), **compute in integer cents** (`Decimal` only where a division/fraction occurs → round half-up to whole cents), **2-decimal euro string in JSON** (unchanged frontend contract). REVERSES the earlier NUMERIC(10,2)-euros decision. | **User decision 2026-07-03**, migration `backend/scripts/migrations/0002_money_to_cents.sql` (applied). Vendor cents stored RAW at ingestion (no ÷100); euros only at the API edge via `app/money.py` (`MoneyIn`/`MoneyStr`). VAT/`pos_fee_pct`/`forecast_qty`/scores stay NUMERIC (fractions/quantities, not money). |
| 6 | Scoring | Seed legacy weights `%sold 0.62 / margin 0.33 / review 0.05`; dual deck model (global 0.55/0.30/0.15 + fridge 0.70/0.30, 50/50) behind `DUAL_SCORING` flag, default off | Parity first, deck model togglable |
| 7 | Table names | **schema.sql (36 tables) is canonical**: `dispatches/dispatch_lines`, `sales_events/restock_events` (partitioned), `weekly_financials`, `product_targets`, `stock_movements`, `order_no_counters` | It exists and is complete |
| 8 | Stock | Append-only `stock_movements` + DB triggers + `v_stock_balances` (all already in schema.sql) | Deck non-negotiable |
| 9 | Sync bookkeeping | **`sync_run` table** (spec 0004) + `fridge_stock`, added by backend as supplemental DDL; incremental jobs re-pull a trailing overlap window and upsert (no separate cursor table). These two are the ONLY bookkeeping tables: there is no `job_runs`, `sync_cursors` or `backfill_checkpoints` | Simplest resumable model; idempotent upserts make overlap free |
| 10 | Dedupe keys | Whatever UNIQUE constraints schema.sql declares on events; where absent, spec 0004 natural keys (`tag_id+purchased_at`, session id) | DB-enforced idempotency |
| 11 | Env keys | `DB_URL` (present in .env), `FRIGOLOCO_API_BASE_URL/USERNAME/PASSWORD/MERCHANT_NAME`; loaded via **python-dotenv** then pydantic-settings; accept `DATABASE_URL` as fallback alias | CLAUDE.md + user confirmation |
| 12 | Weeks | ISO-8601 week + explicit `week_start` DATE everywhere; finance parity deltas vs legacy anchoring documented in tests, not replicated | CLAUDE.md normalisation rule |
| 13 | Fridge live stock | **`fridge_stock`** table (latest-only, PK `(fridge_id, product_code)`, migration `0009_fridge_stock_latest_only.sql`) fed every 15 min by the `snapshot_stock` job via mark-and-sweep; no request-time Husky proxy. **Exactly ONE consumer: `backend/app/services/menu_allocation_service.py`** (snacks/drinks branch `restock = max(target_qty - live, 0)`). There is **no API endpoint and no frontend surface** for it, and no history is retained. Distinct from **warehouse** stock, which is the derived view `v_stock_balances` over `stock_movements` (per product, no fridge dimension) and is what `GET /stock/balances` serves | Request path never calls vendor API (data-sync README); only the newest value per (fridge, product) was ever read, so the append-only log was pure cost |
| 14 | Charts | Frontend uses **d3.js**; mockups stay self-contained inline SVG | User decision 2026-07-03 |
| 15 | Auth | JWT per backend/README is **deferred** - routers ship without auth dependencies for now (single-tenant internal tool); role matrix wired in a later phase | Keeps this phase verifiable end-to-end; flagged in final checklist |

## Load-bearing business formulas (verified against workbooks - do not deviate)

- Sales turnover ex-VAT = `(gross_sales + customer_credit − refunds) / 1.06`
- POS & Software fee = `0.09 × gross_sales` (VAT-INCLUSIVE gross - verified: `=[Total Sales]*Settings!$C$3`)
- RFID fee = `0.10 × items_sold` (rate × items; Excel's rate-only subtraction was a bug - do not replicate)
- Weekly net margin = `(turnover + catering + tgtg) − (fridge_food_cost[ADDED] + catering_food_cost + logistics) − pos_fee − rfid_fee`
- Monthly client net margin = `yearly_fee/12 + food_margin[DISPATCHED] + service_additionals − fraction×logistics − pos_pct×sales`
- Monthly supplier/category net margin = `food_margin − rfid_fee(items)`
- Forecast (legacy parity) = `(cat_sold / (valid_days + no_info_days)) × days_to_fill × (1 + pct_adjust)`; holiday = day with fridge total sold ≤ min_qty (excluded from valid days); 3-week lookback anchored on delivery weekday
- Score (legacy) = `0.62×(sold/added) + 0.33×((sell_ex_vat−buy)/sell_ex_vat) + 0.05×((pos−neg)/(pos+neg))`; UNRECOGNISED tags excluded
- Menu allocation = `round(forecast × score/Σscores)` capped; <0.5→0.51 bump while remainder >0.5; leftover → top-scored; categories Snacks & Drinks use `target − live_stock` instead
- PO: `line = price × qty × (1+vat)`; order ref `YYYY-NNNNN` from `order_no_counters` row-locked; parity anchor order 2026-00360 → 239.36 / 14.36 / 253.72
- Restock verification: `diff = added(VALID, ADDED) − dispatched`; UNRELIABLE counted separately; UNRECOGNISED excluded
- Husky normalisation: cents→`Decimal/100`; `is_refunded` = any refundStatus containing "refunded" (case-insensitive); fridge resolved by BOTH `friendlyName` and `name`; product_code TEXT

## Cron catalogue (merged, APScheduler, Europe/Brussels)

Seven scheduled jobs, exactly as registered in `cron/cron/scheduler.py`, plus one CLI-only entry point. Job ids below are the real ones (`python -m cron.jobs.<name>`).

| Job | Schedule | Purpose |
|---|---|---|
| sync_purchases | hourly :05 | incremental /purchases, trailing 48h overlap, upsert sales_events |
| sync_restock | hourly :10 | incremental /restock ADDED+REMOVED → restock_events |
| snapshot_stock | every 15 min | /stock/current → `fridge_stock`, mark-and-sweep in one transaction, **scoped to the fridges the payload reported on** (upsert every row under a single run-wide `taken_at`, then delete the older-`taken_at` rows **of those fridges only**). A fridge ABSENT from the payload keeps its rows and its old `taken_at`, so it is flagged stale rather than read as empty; an EMPTY payload never sweeps at all. No alerting: the per-fridge 2h freshness check lives in the READER (`menu_allocation_service`), not in this job |
| catalogue_sync | daily 02:00 | /producttype + /fridge + /facility + /fridgeproductprice upserts; absent → is_active=false; Box n° → excluded/test |
| reviews_sync | daily 02:15 | /productreview → product_reviews |
| recompute_scores | daily 02:30 | trailing-365 scores → product_scores (+fridge scores if DUAL_SCORING) |
| partition_maintenance | monthly, 1st 01:00 | pre-create next month's partitions for `sales_events` / `restock_events` / `dispatch_lines` |
| backfill | CLI only (not scheduled) | resumable 7-day-chunk historical pull, raw-first archive, sync_run bookkeeping |

**Alerting jobs are NOT BUILT.** `below_target_alerts`, `expiry_alerts`, `low_stock_alerts`, `rfid_offline_detector` and any email/digest job exist in no code path; the `AlertType` enum declares expiry / low_stock / below_target / rfid_offline, but the only alert ever constructed is `negative_blocked` (`backend/app/services/dispatch_service.py:399`). The Power Automate alert emails these were meant to replace are therefore still NOT replaced, and no alert mail is configured anywhere. Keep them on the roadmap; do not describe them as existing behaviour.

**Fridge-stock freshness (BUILT, in the reader):** `menu_allocation_service` applies `STOCK_READING_MAX_AGE = 2 hours` to the newest `fridge_stock.taken_at`. If the reading is older than 2h (or absent), allocation still runs on the last-known units but every `target_replenish` line is flagged `stock_stale=True` (surfaced via `AllocationLineOut.stock_stale`) and a warning is logged. It is not a cron job, not an alert, not a job status, and not a health endpoint.

Every job: raw-first archive (local `raw_archive/` dir now, blob later), `sync_run` row per run/chunk, per-job advisory lock, idempotent upserts.

## Appendix E - full contradiction list
(Preserved from the doc digest for audit; resolutions above.) 1 Alembic; 2 API prefix; 3 scheduler; 4 cost basis; 5 money type; 6 dual weights; 7 table names; 8 table counts; 9 stock view vs ledger; 10 dedupe keys; 11 cursors; 12 test-mode envs; 13 husky env keys; 14 folder layout; 15 week anchoring; 16 is_active naming; 17 review idempotency; 18 restock filter scope; 19 open questions (0004 Q3/Q9/Q10, 0003 Q3/Q4/Q9, 0002 Q2/Q6).
