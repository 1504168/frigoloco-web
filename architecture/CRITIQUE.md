# FrigoLoco Architecture — Adversarial Critique (CRITICIZER)

> Produced 2026-07-03. Scope: `IMPLEMENTATION-BRIEF.md` (canonical), `system-overview.md`,
> `backend/README.md`, `cron/README.md`, `database/README.md`, `database/schema.sql`,
> root `CLAUDE.md`, the four `mockups/*.html`, and the code actually present under
> `backend/` and `cron/` at review time. This file critiques **decisions**, not typos.
> No existing file was modified.
>
> Rule of engagement for every entry: **named artifact → failure scenario → proportionate fix.**
> Ranked by severity: **S1** (blocks a clean build or a real ops/data risk) → **S4** (polish).
> Verified against source, not inferred: the scaffolded backend (`backend/app/models/*.py`,
> `config.py`, `sync.py`) already follows the **BRIEF**, which means the two architecture
> READMEs are the drifted artifacts, not the code.

---

## What is right (honest signal before the criticism)

These are good calls; do not "fix" them.

- **`schema.sql` is the strongest artifact in the repo.** Append-only signed stock ledger + `BEFORE INSERT` non-negativity trigger with a per-product transaction-scoped advisory lock; append-only guard trigger on UPDATE/DELETE; `next_order_no()` with a row-locked per-year counter; price snapshots on `dispatch_lines`/`purchase_order_lines`; monthly RANGE partitions with the partition key correctly folded into every PK/UNIQUE; `CHECK` sign conventions per movement type. It was applied and behaviorally tested against a scratch PG. This is production-grade DDL.
- **Raw-first ELT + idempotent upsert** (`ON CONFLICT (husky_ref, sold_at) DO UPDATE`, trailing overlap re-pull, `sync_run` audit row per chunk, raw archive before transform) is the correct resumable/auditable design for a no-pagination vendor feed.
- **Design system in the mockups is genuinely good:** one token set, coherent dark mode, semantic color (`--pos/--neg/--good/--warn/--critical`), `font-variant-numeric: tabular-nums` on every number, diverging palette for financial deltas, sticky both-axis matrix headers. It reads as one system.
- **Parity/golden-file testing strategy** with frozen Excel fixtures and named numeric anchors (Salade Cesar `0.6883 ± 0.001`, PO `2026-00360 → 239.36/14.36/253.72`) is exactly how you de-risk an Excel→ERP cutover.
- **Prices-snapshotted-at-transaction-time** and **cancel-with-explicit-reversal** correctly fix two named Excel defects by construction.

---

## S1 — Blocking contradictions and real risks

### S1-1. The scheduler has **three mutually exclusive** homes across the canonical docs
- **Artifacts:** `IMPLEMENTATION-BRIEF.md` #3 + `CLAUDE.md` ("APScheduler … a long-running worker `python -m cron.scheduler` **in its own Docker container**", "code in `cron/`, no scheduled-job code outside `cron/`") **vs.** `cron/README.md` + `backend/README.md` ("APScheduler running **in-process inside the FastAPI web service**", lifespan hook, `SCHEDULER_ENABLED`, code home **`backend/app/jobs/`**) **vs.** `CLAUDE.md` Project Layout bullet ("Each job is a plain CLI entry point **scheduled by Railway cron**" — directly negated three bullets later by "Do **not** use Railway cron schedules").
- **Failure scenario:** an implementer cannot start. The three positions imply different deployment topologies (2 containers vs 1), different single-instance-locking rationales (advisory lock is *mandatory* for a shared web+scheduler process, merely *defensive* for a dedicated worker), different DRY strategies (see S2-6), and **contradictory file locations** — `cron/README.md` puts job code in `backend/app/jobs/`, which `CLAUDE.md` explicitly forbids. Whichever a dev picks, half the docs are wrong and code review stalls.
- **Fix (proportionate):** the BRIEF already won — pick **dedicated `cron/` container running `python -m cron.scheduler`**. Then: (a) delete the in-process/lifespan scheduler description from `cron/README.md` §3 and `backend/README.md` §2/§4c and the `jobs/` folder from the backend tree; (b) delete the "Railway cron" bullet from `CLAUDE.md`; (c) demote the advisory lock from "guards Railway replica double-scheduling" to "guards rolling-deploy overlap of the single worker." One decision, three deletions.

### S1-2. **Alembic is forbidden by the canonical decision but still mandated by three architecture docs**
- **Artifacts:** `CLAUDE.md` ("**NO Alembic — explicit decision** … do not recommend it") and `IMPLEMENTATION-BRIEF.md` #1 (plain SQL via `apply_schema.py`) **vs.** `backend/README.md` (header "SQLAlchemy 2 + **Alembic**"; `alembic/` in the tree; "stock trigger lives in **Alembic migration 0001**"), `system-overview.md` ("land as the **first Alembic migration** in Phase 1"), `database/README.md` ("turns it into `alembic/versions/0001_*.py`"). Ten Alembic references remain in `architecture/`.
- **Failure scenario:** a new engineer follows `backend/README.md`, runs `alembic init`, and now there are two competing schema-of-record mechanisms (SQL file vs migrations). The `base.py`/`sync.py` `create_all(checkfirst=True)` path silently diverges from an Alembic history nobody is maintaining.
- **Fix:** strip every Alembic mention from the three docs; replace with the `apply_schema.py` + numbered-SQL-scripts model already implemented. The scaffolded `backend/app/models/base.py` already documents the correct approach — the READMEs just weren't updated.

### S1-3. **Four overlapping mockups, no single frontend source of truth**
- **Artifacts:** `mockups/frigoloco-{dispatch,supply,returns,forecasting}-app-mockup.html`. `system-overview.md` names only **three** (dispatch, supply, returns) and never mentions `frigoloco-forecasting-app-mockup.html` — which is the **largest (116 KB)** and is a *superset megaapp*: its nav (`Planning / Operations / Insights / System`) re-implements Dispatch, Purchase Orders, Stock, Verification, and Clients that already exist as standalone pages in the dispatch/supply apps, and adds Dashboard, Ratings, and Reports the others lack.
- **Failure scenario:** "the React app implements these" (system-overview) is undefined for any feature that appears twice. When a dev builds the Stock page, do they follow `supply-app` or `forecasting-app`? The two can — and by review time already do — diverge in layout, column sets, and even category ordering. The team builds one page twice and reconciles later, or ships an inconsistent app.
- **Fix:** declare **one** canonical IA. Cheapest correct answer: the `forecasting-app` megaapp *is* the real single-SPA information architecture (its `Planning/Operations/Insights/System` grouping is the most complete); the other three are per-domain design studies. State that explicitly in `system-overview.md`, and mark dispatch/supply/returns as "detail references for pages X/Y/Z, superseded for navigation." Then the page→endpoint→service table maps to *one* nav tree.

### S1-4. Confirm-dispatch does **file rendering + blob upload inside the DB transaction**, and a PDF failure **rolls back a physical stock deduction**
- **Artifact:** `backend/README.md` §4a — "Everything up to and including the `generated_documents` rows is one DB transaction. A failure at … document rendering or Blob upload rolls back the status flip, the stock movements, and the price snapshots." The transaction holds per-product advisory locks (from the non-negativity trigger, 428 lines) while WeasyPrint renders 42 PDFs and uploads them to Azure Blob over the network.
- **Failure scenario (two distinct):** (1) **Scalability/locking** — a slow blob upload keeps a Postgres transaction and per-product advisory locks open for many seconds, blocking every concurrent stock movement on those products and pinning a DB connection; under any real concurrency this serializes the warehouse. (2) **Correctness** — the goods were physically loaded and dispatched; a transient WeasyPrint/Blob error should not *un-dispatch* stock. The design already accepts this exact reasoning for email ("a bounced email must never un-dispatch stock") but then contradicts it for documents.
- **Fix:** commit the stock deduction + status flip + price snapshots as the transaction; move document generation **and** email **after commit**, exactly like email already is. On render/upload failure, leave the dispatch `dispatched` with a `documents_pending` flag and an `alerts` row; a small retry job (or the existing digest) regenerates. This shortens the locked transaction to microseconds and stops a formatting bug from reversing a real-world delivery.

---

## S2 — Significant

### S2-1. The two architecture READMEs describe a **different sync/persistence model than the code being built**
- **Artifacts:** `cron/README.md` + `backend/README.md` are built on `sync_cursors` (one row/feed, `last_synced_at`, "cursor advances only after commit") plus support tables `job_runs`, `backfill_checkpoints`, `live_stock_snapshot`, `generated_documents`, `reconciliation_daily` (six, per system-overview's "known delta"). **The actual code** (`backend/app/models/sync.py`, and `IMPLEMENTATION-BRIEF.md` #9) has **`sync_run` + `stock_snapshots` only, and explicitly *no cursor table*** ("incremental jobs re-pull a trailing overlap window and upsert — no separate cursor table"). `base.py` states "**only the two sync tables** … are created from metadata."
- **Failure scenario:** a dev implementing the hourly sync from `cron/README.md` writes cursor-advance logic against a table that will never exist, and models four support tables the persistence layer doesn't have. Every sequence diagram in `backend/README.md §4c` references `sync_cursors`.
- **Fix:** rewrite `cron/README.md`'s idempotency column and §3.2/§4 and `backend/README.md §4c` to the trailing-overlap-window + `sync_run` model. Fold `job_runs` semantics into `sync_run` (it already has `job`, `status`, `records_*`, `error`, timings). If `generated_documents`/`reconciliation_daily` are still wanted, add them as numbered supplemental SQL, but stop citing tables the schema-of-record and code don't define.

### S2-2. `CLAUDE.md`'s own "Verified Domain Facts" contradict the canonical money decision
- **Artifacts:** `CLAUDE.md` → "**Store money as integer cents (`bigint`)** … convert only at the UI layer" **vs.** `schema.sql` (`NUMERIC(10,2)` euros everywhere) and `IMPLEMENTATION-BRIEF.md` #5 (NUMERIC euros in DB, `Decimal` in Python, decimal strings in JSON).
- **Failure scenario:** `CLAUDE.md` is loaded as an override-everything instruction in every session; a future agent "corrects" a `Numeric(10,2)` column to `BigInteger` cents to obey it, breaking the applied schema and every parity fixture.
- **Fix:** amend the one `CLAUDE.md` bullet to: "Husky cents are converted to `Decimal` euros at the sync boundary (`Decimal(str(v))/100`); the DB stores `NUMERIC(10,2)` euros (integer-cents preference is on record but consistency with the applied schema wins)." Keep the historical note, remove the standing instruction.
- **Adjacent risk:** `NUMERIC(10,2)` caps at ±99,999,999.99. Per-row (PO totals, line prices, weekly inputs) this is safe forever. Confirm the **monthly-analysis live aggregations** over 20–30 M events are summed in Python `Decimal` (they are, per `finance.py` "computed live … no stored aggregate tables"), so no column ever holds the sum — good, but state it so nobody adds a `NUMERIC(10,2)` cached total that overflows on an annual roll-up.

### S2-3. `backend/README.md` is stale against the scaffolded code on **folder layout and env vars**
- **Artifacts vs. reality:**
  - Folder tree lists `models/{catalogue,clients,orders,dispatch,events,finance,system}.py`; the actual split is `models/{master,operations,planning,events,sync}.py`. Every "one file per aggregate" mapping is wrong.
  - §6 marks **`DATABASE_URL`, `HUSKY_BASE_URL`, `HUSKY_USER`, `HUSKY_PASSWORD`, `JWT_SECRET`, `AZURE_BLOB_CONN`, `EMAIL_*`** as required. Actual `config.py` reads **`DB_URL`, `FRIGOLOCO_API_BASE_URL/USERNAME/PASSWORD`, `FRIGOLOCO_MERCHANT_NAME`** and has **no** JWT/Azure/email/`DATABASE_URL` keys at all.
  - §3.11 comment claims the Husky client does "retry/backoff, **pagination**" — but `CLAUDE.md` verified "**No pagination anywhere**" on the Intelligent Fridges API. Writing a pagination loop against a windowed-only API is dead code at best, an infinite loop at worst.
- **Failure scenario:** onboarding devs configure the wrong env keys (app fails to boot on missing `DATABASE_URL` that was renamed `DB_URL`), build a models layout that doesn't match imports, and implement pagination that the API doesn't support.
- **Fix:** regenerate `backend/README.md` §2 and §6 from the actual `models/` and `config.py`; change the §3.11 comment from "pagination" to "date-window chunking (no pagination — vendor is windowed only)."

### S2-4. "No auth for now" on an **internet-facing mobile driver surface that carries client site-access secrets**
- **Artifacts:** `IMPLEMENTATION-BRIEF.md` #15 (routers ship with no auth deps) + the Driver View mockup, which renders **door/badge instructions, floor location, and a site phone number** ("⚠ Badge à l'accueil · frigo au −1 … sonner au 02 737 xx xx si fermé") plus every client's delivery address.
- **Failure scenario:** for a desktop-only internal tool, deferring auth is defensible. But drivers hit this from phones in the field, so the service is on the public internet. With zero auth, any leaked/guessed URL exposes physical access instructions and door codes for every client site — a real security exposure, not just a data-privacy nicety.
- **Fix:** you don't need the full JWT role matrix now, but ship **one** gate before the driver view is reachable off-LAN: a single shared bearer token / Cloudflare Access / basic-auth in front of the SPA, or scope the driver route behind a signed, short-TTL per-dispatch link. Keep the role matrix deferred; add a checklist line "driver surface must not be anonymously reachable from the internet."

### S2-5. The **returns mockup encodes business-logic errors the brief already overturned** — and it's what the app "implements"
- **Artifacts:** `mockups/REVIEW-returns-mockup.md` documents three verified errors in `frigoloco-returns-app-mockup.html`: weekly fridge food cost uses **dispatched** basis (should be **ADDED/restock**), POS 9% is charged on **ex-VAT** turnover (should be **VAT-inclusive gross**, ~6% understatement), and the deliberate weekly-ADDED vs monthly-DISPATCHED basis split is erased. `IMPLEMENTATION-BRIEF.md` #4 and the load-bearing-formulas section fix all three — but the *mockup pixels* still show the wrong ones, and `system-overview.md` says "the React app implements these" mockups.
- **Failure scenario:** a dev builds the weekly P&L page pixel-faithfully from the mockup and reintroduces the exact fee/basis bugs the verifier caught, which the parity fixtures may not cover if the fixture set is monthly-heavy.
- **Fix:** annotate the three offending regions of `frigoloco-returns-app-mockup.html` inline ("basis = ADDED, not dispatched — see BRIEF formula"), or add a "known-wrong, see REVIEW-returns-mockup.md + BRIEF §formulas" banner to that mockup. Cheapest: link `REVIEW-returns-mockup.md` from the BRIEF so the fix travels with the spec, not just the mockup folder.

### S2-6. **DRY across `backend/` and `cron/` is unresolved** — forecast/scoring/finance are needed by both
- **Artifacts:** `forecast.py`, `scoring.py`, `finance.py` are invoked on-demand by API routers **and** nightly by cron (`auto_forecast`, `recompute_product_scores`, `daily_husky_reconciliation`). `CLAUDE.md` forbids code sharing across segments ("no API code outside `backend/`, no scheduled-job code outside `cron/`"). With the S1-1 dedicated-container decision, `cron/` cannot `import app.services.forecast` without depending on the backend image.
- **Failure scenario:** teams either (a) duplicate the forecast/scoring/finance engines in `cron/` (guaranteed drift; parity fixtures pass in one place and rot in the other) or (b) quietly violate the segmentation rule.
- **Fix:** name a **shared domain package** (`frigoloco_core/` or `backend/app/domain/` published as an installable) that both `backend/` and `cron/` depend on; routers and jobs are thin adapters over it. Decide this now — it's the single most consequential structural choice for maintainability and neither README addresses it.

---

## S3 — Moderate

### S3-1. Non-negativity trigger re-`SUM`s the **entire per-product ledger on every insert**
- **Artifact:** `enforce_stock_non_negative()` does `SELECT COALESCE(SUM(qty),0) … WHERE product_id = NEW.product_id` on each `BEFORE INSERT`. Confirm-dispatch inserts up to 428 rows in one transaction, each firing a full-history sum for its product; the ledger grows unbounded (weekly dispatches × 200 fridges, for years).
- **Failure scenario:** insert cost grows O(history-per-product); years in, each confirm is summing tens of thousands of movements per product under an advisory lock. Not a day-one problem; a definite year-three one.
- **Fix (defer, but design for it):** keep the trigger, but bound the scan with a periodic **balance checkpoint** row per product (e.g., monthly `adjustment`-typed "carry-forward" the janitorial job writes) so the trigger sums only movements since the last checkpoint; or maintain a `product_balances` materialized counter updated in the same statement. `ix_stock_movements_product_created` helps the scan but doesn't bound its growth.

### S3-2. Nightly scoring/reconciliation **full-scan 12 monthly partitions on the same Postgres that serves the API**
- **Artifact:** `recompute_product_scores` (trailing-365-day, all products) + `daily_husky_reconciliation` (per-fridge yearly counts) over `sales_events`/`restock_events` at 20–30 M rows.
- **Failure scenario:** a heavy 02:30 aggregation competing with morning API traffic causes latency spikes — badly compounded if S1-1 had left the scheduler *in-process*. Even with a separate worker, it's the same database instance.
- **Fix:** the partition design already helps (prune to 12 children). Add: run the nightly aggregates with a lower work priority / off-peak window (02:00–03:00 is already chosen — good), and consider a read replica later if the single instance saturates. Mainly: make the S1-1 "separate worker" decision *because* of this, and document the shared-instance contention as a known limit with the replica escape hatch.

### S3-3. **Category taxonomy is inconsistent** across schema seed, mockups, and `documents.py`
- **Artifacts:** `schema.sql` seed `display_order`: `1 Cold, 2 Warm, 3 Warm Jar, 4 Wraps, 5 Breakfast & Granolas, 6 Soup, 7 Desserts, 8 Drinks, 9 Snacks, 10 Frozen Warm`. Dispatch/menu mockup chip-strip: `1 Cold, 2 Wraps & Sandwiches, 3 Warm Jar, 4 Warm, 5 Desserts, 6 Snacks, 7 Drinks, 8 Breakfast, 9 Soups, 10 Frozen Warm` — **different numbers and names for the same categories**. `backend/README.md §3.9` prints the driver sheet order as a **9-item** list ("Hot → Frozen → Salads → Wraps → Granolas → Soups → Desserts → Drinks → Snacks") that omits "Warm Dishes Jar"; `schema.sql`'s `dispatch_print_order` is a **10-item** ordering.
- **Failure scenario:** driver delivery sheets (R8) sort by `dispatch_print_order`; if a dev hardcodes category order/labels from the mockup or the 9-item README list, the printed sheet no longer matches the fridge shelf layout — the whole point of R8 — and category filters key off numbers that don't exist in the DB.
- **Fix:** `categories` (with its seeded `display_order`/`dispatch_print_order`) is the single source. Regenerate the mockup chip labels and the `documents.py` print-order list from the seed; delete the ad-hoc 9-item list in `backend/README.md`.

### S3-4. **Table count disagrees across the canonical docs (27 vs 34 vs 36)**
- **Artifacts:** `system-overview.md` "~27 tables"; `database/README.md` "34 tables total"; `IMPLEMENTATION-BRIEF.md` #7 "schema.sql (36 tables)". Verified count of `CREATE TABLE IF NOT EXISTS` in `schema.sql` = **34** base tables (+ 50 partition children, + 2 supplemental sync tables in code = 36 if you count those).
- **Failure scenario:** trivial confusion, but it's a canary — three "authoritative" docs can't agree on a countable fact, which erodes trust in the rest.
- **Fix:** state it once, unambiguously: "34 base tables in `schema.sql` + 50 pre-created monthly partition children + 2 supplemental sync tables (`sync_run`, `stock_snapshots`) created from ORM metadata = 36 relations total." Reference that line everywhere.

### S3-5. `config.py` **doesn't implement the `DATABASE_URL` fallback the BRIEF mandated**
- **Artifact:** `IMPLEMENTATION-BRIEF.md` #11 "accept `DATABASE_URL` as fallback alias." `config.py` binds `db_url` to `validation_alias="DB_URL"` only — no `AliasChoices("DB_URL","DATABASE_URL")`.
- **Failure scenario:** Railway injects `DATABASE_URL` by default for managed Postgres; a deploy that relies on that (or a contributor following `backend/README.md §6` which lists `DATABASE_URL` as *the* key) boots with a missing-required-var crash.
- **Fix:** `db_url: str = Field(validation_alias=AliasChoices("DB_URL","DATABASE_URL"))`. One line; matches the already-imported `AliasChoices`.

---

## S4 — Minor / polish

- **S4-1. `next_order_no()` derives the year from `EXTRACT(YEAR FROM CURRENT_DATE)` in the DB session tz.** If the DB runs UTC while ops is `Europe/Brussels`, a PO created just after midnight Brussels on Jan 1 draws the *previous* year's `YYYY-NNNNN`. Fix: `EXTRACT(YEAR FROM (now() AT TIME ZONE 'Europe/Brussels'))`. Matters for year-rollover parity tests.
- **S4-2. `dispatches` `UNIQUE(delivery_date)` allows exactly one batch per calendar date globally.** Re-saving replaces lines (intended), but you can never model two independent runs on the same date (e.g., a planned morning route + an ad-hoc afternoon top-up). If that never happens operationally, fine — but document the constraint as deliberate so nobody treats a "second dispatch today" as a bug.
- **S4-3. Frontend matrix scale.** At 200 fridges × the week's menu products (~60–80) the grid is ~14 K editable cells with both-axis sticky headers; the mockup's "every fridge loads in this one virtualized grid" is a nontrivial d3/DOM virtualization job (sticky rows *and* columns + per-cell edit + column totals). Budget for it explicitly; consider windowing rows only and paginating fridges by route.
- **S4-4. Type drift, low stakes:** `ForecastCellResult.forecast_qty: int` (backend README dataclass) vs `forecast_results.forecast_qty NUMERIC(10,2)` (schema stores fractional, correct — round at allocation); `product_reviews.husky_ref` is `UNIQUE` but **nullable**, so Excel-migrated reviews with no ref won't dedupe on re-import. Align the dataclass comment; give migrated reviews a synthetic deterministic `husky_ref`.
- **S4-5. `auto_forecast` snacks/drinks allocation reads the live snapshot without a freshness gate**, while `below_target_alerts` correctly skips on `snapshot stale > 2h`. A stale snapshot at the Wed-15:00 auto-run silently over/under-fills target-based categories. Apply the same staleness guard to the snacks/drinks branch of `menu_allocation.compute_target_replenishment`.
- **S4-6. Mobile scope is driver-only (intended), but the dense ops grids are desktop-only** (matrix `min-width: 1180px`). If any warehouse/ops work happens on a tablet, those pages force horizontal scroll. Confirm ops is desktop-only; if not, the matrix needs a tablet fallback.

---

## Severity roll-up

| # | Lens | Severity | One-line |
|---|------|----------|----------|
| S1-1 | Maintainability | S1 | Scheduler has 3 contradictory homes (in-process / own container / Railway cron) + 2 code locations |
| S1-2 | Maintainability | S1 | Alembic forbidden by canon, still mandated by 3 architecture docs |
| S1-3 | Aesthetic/IA | S1 | 4 overlapping mockups, no single frontend source of truth; megaapp omitted from overview |
| S1-4 | Functional/Scalability | S1 | Doc render + blob upload inside the dispatch DB txn; PDF failure un-dispatches physical stock |
| S2-1 | Maintainability | S2 | READMEs describe `sync_cursors`/6 support tables; code+BRIEF use `sync_run`/`stock_snapshots`, no cursor |
| S2-2 | Maintainability | S2 | `CLAUDE.md` says integer-cents; schema+BRIEF say NUMERIC euros |
| S2-3 | Maintainability | S2 | `backend/README.md` stale: folder layout, env vars, "pagination" on a no-pagination API |
| S2-4 | Functional/Security | S2 | No-auth driver view is internet-facing and leaks site door codes/addresses |
| S2-5 | Functional | S2 | Returns mockup encodes 3 overturned P&L bugs the app is told to implement |
| S2-6 | Maintainability | S2 | Shared forecast/scoring/finance across backend+cron has no DRY home |
| S3-1 | Scalability | S3 | Non-negativity trigger sums full per-product ledger every insert |
| S3-2 | Scalability | S3 | Nightly 365-day scans on the API's own Postgres |
| S3-3 | Functional | S3 | Category numbering/names/print-order inconsistent across seed, mockups, README |
| S3-4 | Maintainability | S3 | Table count stated as 27 / 34 / 36 |
| S3-5 | Functional | S3 | `config.py` missing the `DATABASE_URL` fallback the BRIEF required |
| S4-1..6 | mixed | S4 | order-no tz, one-batch/date rigidity, matrix virtualization scale, type drift, snapshot freshness gate, tablet |

**Bottom line.** The database layer and the ELT/idempotency design are excellent and should not be touched. The single largest liability is **documentation drift**: `backend/README.md` and `cron/README.md` were written before the verifier's BRIEF and now describe a superseded system (Alembic, in-process scheduler, `sync_cursors`, JWT/Azure env vars, a wrong models layout) — while the actual scaffolded code already tracks the BRIEF. Reconcile the two READMEs to the BRIEF + code, make the three S1 decisions (scheduler home, no-Alembic cleanup, one canonical mockup IA), and move document generation out of the confirm transaction. Everything else is S3/S4 and can wait.
