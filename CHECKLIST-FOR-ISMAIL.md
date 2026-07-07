# FrigoLoco — Status, Assumptions & Your Checklist

## ⚡ Addendum — Workflow rework session (2026-07-03, later)

Everything below in the original checklist still applies. Since then, the D1–D6 rework shipped and was validated (`architecture/REWORK-VALIDATION.md`, no FAILs):

- **React app is live** — backend **:8100**, frontend **:5173** (port 8000 freed at your request). Run: `cd backend && .venv/bin/uvicorn app.main:app --port 8100 --reload` + `cd frontend && npm run dev`.
- **Your decisions executed**: integer-cents money (live migration, euro-string API kept), `native_enum=False` (all PG enums → text+CHECK), partitioned `dispatch_lines`, APScheduler (+ monthly partition-maintenance job), d3 charts, FrigoLoco branding (teal `#45BCB4` dark / AA `#1A8175` light, logo sidebar, pin favicon).
- **Pipeline rebuilt** per your Excel workflow: Forecast → Menu → Dispatch keyed on (year, week, day) with import-from-previous / save / load-saved / overwrite-confirm; dispatch SAVE = planned (stock untouched — validator-proven), Create Individual Dispatch = the only stock-reducing step; Excel-like grids with cascading pickers and configurable columns-per-category; Fridge Report + Excel export (summary on top); 18-column Product Rating page; Husky sync buttons with `local_status` overrides that survive syncs (live-proven).
- **Bugs found & fixed by the verify loops**: supplier links lost (now 39 suppliers / 571 products linked), purchase prices never ingested (Husky `reference` is a decimal string — now 573 products carry real buy prices; margins finally vary), Py3.14 FastAPI body-annotation bug in the envelope decorator.
- **Test suites: 58 backend + 50 cron green**; frontend build clean; all synthetic test data neutralised with audited adjustments.

### Your immediate actions (rework-specific)
1. **Seed fridge delivery configs** (Masters → Fridges → delivery-config editor: weekday + min qty + days-to-fill per fridge). This is the ONE gate keeping the Forecast page dark — everything downstream works once configured.
2. **Drop the official logo file** into `frontend/public/` (placeholder SVG in use).
3. Known nits queued for next pass: scorecard shows margin 1.0 for products with no buy price (should be excluded/null); export headers unbranded; collapsed-sidebar pin mark missing; ~630 kB JS bundle wants code-splitting.

> Written by the verifier session, 2026-07-03, after the autonomous build run you authorized.
> Companion docs: `architecture/IMPLEMENTATION-BRIEF.md` (canonical decisions), `architecture/CRITIQUE.md`, `architecture/QA-QUESTIONS.md`, `mockups/AUDIT-coverage.md`, `architecture/database/REVIEW-schema-vs-deck.md`.

## ✅ What is built and verified

| Layer | State |
|---|---|
| **Database** | schema.sql applied to Railway Postgres: 34 base tables + 122 monthly partitions + 2 sync tables + `v_stock_balances`; stock non-negativity + append-only triggers live; seeds loaded |
| **Historical backfill (spec 0004's goal)** | **COMPLETE**: 333,780 sales events (earliest 2022-05-25), 501,898 restock events (earliest 2022-05-18), 5,626 reviews (earliest 2024-02-18) — the full business history from the pilot install to today; 930 gzipped raw payloads archived (raw-first ELT); `sync_run` bookkeeping clean (stale attempt rows annotated, zero unexplained data loss) |
| **Backend API** | FastAPI on `/api/v1`: ~70 routes across 14 routers (masters, menus, forecasts, scoring, dispatches+confirm, stock, purchase orders+receive/cancel, verifications, finance weekly/monthly/GSV, alerts, settings); 25 tests green incl. PO parity anchor (2026-00360 → 239.36/14.36/253.72); smoke-tested live against Railway |
| **Cron layer** | `cron/` package: Husky client (throttle/retry/typed), 7 jobs (all CLI + APScheduler worker `python -m cron.scheduler`, Europe/Brussels); live-verified: catalogue (577 products), fridges (47), clients (51), stock snapshots, scores (95) |
| **Mockups** | 4 files, one design system, drift fixed; all 6 returns-mockup formula errors corrected; print styles (driver sheet = one fridge/page), a11y labels, empty/error states added; coverage map + canonical IA in `mockups/AUDIT-coverage.md` |

## ⚠️ Assumptions I made on your behalf (review these)

1. **Vendor category taxonomy wins.** The schema seed had wrong category numbering vs Husky's real one; I renumbered the live DB to the vendor taxonomy (11 categories incl. `Uncategorised`) keeping the deck's driver-sheet print order. → **schema.sql's seed block still needs the same fix** or a fresh apply recreates the drift.
2. **Money = NUMERIC(10,2) euros in DB** (not integer cents), matching the applied schema; single cents→euros conversion at the Husky sync boundary. Recorded in CLAUDE.md.
3. **Auth is deferred** — the API has NO authentication. Fine on localhost; **do not expose it (especially driver views with door codes/addresses) to the internet before adding a gate** (criticizer S2-4).
4. **440 stub products** were auto-created (inactive, `Uncategorised`) for discontinued 2022–2024 items so no history was dropped. They need no action but will appear in unfiltered product lists.
5. **Restock UNCHANGED + UNRECOGNISED tag events are not stored** (enum/NOT NULL constraints). Counted per window as `unchanged_unrepresentable`. The deck's residual-stock/withdrawal feature may later need an enum value added.
6. **Reviews idempotency** uses a synthesized ref (vendor exposes no review id).
7. **Husky report endpoints reject windows ending <5 min ago** — sync clamps to now−6min (that's why "yesterday's data" can lag a few minutes).
8. **Monthly logistics allocation** is simplified (client share × logistics) — the Excel `Fraction List`/month-grain table has no schema home yet.
9. **Forecast `no_info_days` isn't persisted** (schema lacks the column); the math uses it correctly.
10. **2022–2024 event partitions** were created live by me (schema.sql only shipped 2025+); the partition-maintenance job should own future months.
11. **Scoring weights seeded at legacy 0.62/0.33/0.05**; the deck's dual model exists behind a `DUAL_SCORING` flag, default off.
12. **Legacy Excel weeks → ISO weeks + `week_start`** in the DB; finance parity vs legacy anchoring is tolerance-tested, not replicated bug-for-bug.

## ✋ Needs your explicit sign-off

- **Wix auto-pull of weekly inputs**: the mockups/backend re-architect Total Sales/Refund/Discount/Credit as auto-computed from synced sales events instead of manual weekly entry. Approve or revert.
- **RFID-fee historical restatement** (spec 0003 Q3): recompute history with the corrected `€0.10 × items` formula, or replicate the Excel bug for continuity?
- **Husky password rotation plan** (spec 0004 Q6): plaintext creds are still in 10 Office Scripts; rotating breaks live Excel. Recommend requesting a dedicated integration user from the vendor.

## 📋 What you should check (in order)

1. **Open the spec** `specs/0004-.../..._v1.html` — answer the remaining open questions (Q1–Q3, Q5–Q11; Q4 answered = APScheduler). Snapshot cadence (Q3) and retention (Q10) matter most now that snapshots run.
2. **Read `architecture/QA-QUESTIONS.md` §3** — 16 questions nobody asked: NL (Dutch) localisation, backups/DR, GDPR retention, driver mobile auth, email provider, TGTG + Wix integration mechanics, user management.
3. **Spot-check the data**: open the API (`cd backend && .venv/bin/uvicorn app.main:app`) → `/api/v1/finance/monthly?dimension=client&month=2026-06` and compare a few fridges against your Excel return workbook.
4. **Review `architecture/CRITIQUE.md`** — S1/S2 items not yet closed: doc-drift rewrite of the two READMEs (banners added, full rewrite pending), PDF generation kept out of the confirm transaction when it's built.
5. **Sanity-check the mockups in a browser** (all four in `mockups/`) — especially the corrected returns formulas and the print preview of the driver sheet.

## 🔜 Remaining scope (not yet built)

- **Excel history importer** (dispatch history ~20.7k lines, 513 POs, 50+ weekly summaries, targets/fees/fractions) — spec 0004 Phase 6; needed before Excel retirement and for `fridge_delivery_config` (forecast endpoint correctly errors until delivery weekdays are configured).
- **React frontend** (`frontend/` is a placeholder) — build from the mockups' canonical IA; d3.js for charts.
- **Deployment**: backend + APScheduler worker containers to Railway (both Dockerfiles exist); blob storage account (raw archive currently writes to local disk via `RAW_ARCHIVE_DIR`).
- **Auth/roles**, document generation (PDF driver sheets / PO emails), alert email digests, weather ingestion (spec Q11).
