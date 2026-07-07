# Frigoloco

Excel-based operations tooling for Frigoloco smart fridges: Office Scripts (in `Office Scripts/`) that manage weekly data, dispatch, purchase orders, forecasts, and restock alerts, backed by the Intelligent Fridges API and Power Automate flows.

## Project Layout

This is a Python + React monorepo. All application code MUST go in its respective segment — do not mix segments (no React code outside `frontend/`, no API code outside `backend/`, no scheduled-job code outside `cron/`).

- `frontend/` — React + TypeScript + shadcn/ui + Vite web app. All UI code lives here.
- `backend/` — FastAPI + SQLAlchemy 2.0 (Python 3.12) REST API. All API/business-logic code lives here.
- `cron/` — scheduled jobs (Python 3.12): Husky API syncs, stock snapshots, backfills. Each job is a plain CLI entry point; scheduling is done by the APScheduler worker (`python -m cron.scheduler`) — NOT Railway cron (user decision 2026-07-03).
- `Office Scripts/` — legacy Excel Office Scripts extracted as plain `.ts` files (one `main(workbook: ExcelScript.Workbook)` entry point each). Git-ignored because they currently contain hardcoded credentials/webhook signatures. Reference-only — no new development here.
- `Excel Files/` — workbook files the legacy scripts run against.
- `mockups/` — HTML UI mockups.
- `specs/` — spec documents (folder-based structure per global spec conventions).
- `architecture/` — architecture docs.

### Docker

Each code segment (`frontend/`, `backend/`, `cron/`) MUST have its own `Dockerfile` and run as a container — local development and Railway deployment both go through Docker. Use a root `docker-compose.yml` to orchestrate the three services (plus Postgres for local dev). Never install/run a segment directly on the host as the primary workflow; if you add a dependency, it goes in that segment's dependency file and its image, not the host machine.

## Environment Variables

All secrets and environment-specific config live in `.env` (git-ignored). Never hardcode these values in scripts, specs, or docs — reference the key names instead.

### Intelligent Fridges API (Basic Auth)

| Key | Purpose |
|-----|---------|
| `FRIGOLOCO_API_USERNAME` | Basic Auth username for the Intelligent Fridges API |
| `FRIGOLOCO_API_PASSWORD` | Basic Auth password for the Intelligent Fridges API |
| `FRIGOLOCO_API_BASE_URL` | API base URL (`https://api.intelligentfridges.com/api/v1`) |
| `FRIGOLOCO_MERCHANT_NAME` | Merchant URL segment used in API paths (default `frigoloco`) |

Used by the API-calling scripts: Add Or Update Weekly Data, Create Purchase Order, Create Individual Dispatch, Refresh Stock And Ordered, Refresh Drinks And Snacks, Update Forecast, Update Rating, Update Order History, Send Restock Verification Alert, Genereate Fridge Specific Food Cost And Rev Report, Get Below Target Items.

### Power Automate Webhook Endpoints

Each URL embeds a `sig=` signature and must be treated as a secret — anyone with the URL can trigger the flow.

| Key | Flow | Used by |
|-----|------|---------|
| `PA_WEBHOOK_CREATE_PO_URL` | createpo | Create Purchase Order |
| `PA_WEBHOOK_UPDATE_DISPATCH_FILE_URL` | updatedispatchfile | Create Individual Dispatch |
| `PA_WEBHOOK_DISPATCH_RETURN_URL` | dispatch return (shared) | Send Dispatch Data To Return File, TestScript |
| `PA_WEBHOOK_RESTOCK_ALERT_URL` | restock verification alert | Send Restock Verification Alert |

### Database

| Key | Purpose |
|-----|---------|
| `DB_URL` | PostgreSQL connection URL for the Railway-managed database (system of record) |

Connection verified 2026-07-03: Railway Postgres via `turntable.proxy.rlwy.net:25669`, PostgreSQL 18.4, database `railway`, user `postgres`. Never print or commit the password — always mask credentials in logs/output.

### Misc

| Key | Purpose |
|-----|---------|
| `TEST_SUPPLIER_EMAIL` | Supplier email substituted when `OrderSheetIsTestRun` is true (used in `SUPPLIER_EMAIL_FORMULA` in Reset Order View For Manual Order and Pull Order Details From Menu Sheet) |

## Constraints

- Office Scripts running inside Excel have **no access to `process.env` or `.env` files**. When a script must run in the Excel sandbox, inject these values as `main()` parameters (e.g., from Power Automate) instead of reading env vars.
- Some scripts still hardcode the full API URL inline instead of using a base-URL constant (e.g., `Update Forecast.ts`) — substitute `FRIGOLOCO_API_BASE_URL` when refactoring.

## Target System (Cloud ERP) — Verified Domain Facts

These facts were verified against the live Intelligent Fridges OpenAPI spec (preserved copy: `specs/0004-database-setup-and-husky-historical-backfill_2026-07-02_0810PM_UTC/reference-docs/intelligentfridges_openapi_v1.json`), the Office Scripts source, and the two workbooks. Do not re-derive them; do not contradict them.

### Vendor API ("Husky" = Intelligent Fridges)
- The deck says "Husky"; the API is `https://api.intelligentfridges.com/api/v1/{merchant}` — "Intelligent Fridges API" v1, OpenAPI 3.0.1. **Not** huskyintelligence.com (unrelated company).
- HTTP **Basic auth only**. **No pagination anywhere** — event endpoints (`/purchases`, `/restock`, `/productreview`) are windowed by `from`/`to`; chunk large pulls by date range (7-day windows proven safe).
- **The Husky API returns prices as `int64` minor units (cents)** in every schema. **DECIDED (2026-07-03, reversing the earlier NUMERIC(10,2)-euros note): the database stores money as `BIGINT` integer minor units (cents)**, matching the Husky int64 contract (migration `backend/scripts/migrations/0002_money_to_cents.sql`, applied; reflected in `architecture/database/schema.sql`). Vendor cents are stored **RAW** at ingestion — NO `÷100` at the sync boundary. Euros exist only at the API presentation edge: JSON still serialises money as a 2-decimal euro string (e.g. `"9.60"`) via `app/money.py` (`MoneyStr` out, `MoneyIn` in), so the frontend contract is unchanged. Compute in integer cents; use `Decimal` only where a division/fraction is unavoidable (VAT split, margin, fee %), then round half-up to whole cents. VAT rates / `pos_fee_pct` / `forecast_qty` / scores stay `NUMERIC` (they are fractions/quantities, not money). Do not "fix" the schema back to NUMERIC euros.
- `GET /{m}/stock/current` is **point-in-time only** — stock history cannot be backfilled; the snapshot cron is time-critical.
- Beyond the deck's 4 endpoints, the API has 26 GET paths incl. `/fridge` (maps `if-XXXXXXX` hardware ids ↔ friendly names), `/fridgeproductprice` (per-fridge price overrides), and live device telemetry (`/fridge/{name}/state|temperature|products|tags`) usable for the "RFID offline" alert.

### Data rules
- `product_code` is **TEXT**, never numeric — EANs with leading zeros coexist with short codes (`1001`).
- Fridges join by `friendly_name` in Excel but have hardware ids (`if-0001120`); the DB keeps both and joins by id. Known name drift exists (`Thermofisher` vs `Thermofisher Vilvoorde`) — imports must fail loudly on unmapped names.
- **Three week-numbering schemes** coexist in the legacy scripts (custom Jan-1-anchored, ISO-8601, weekday-anchored). The DB normalises to ISO week + an explicit `week_start` date column.
- Verified business constants (parameterise, never hardcode): food VAT 6%; POS & Software fee 9% of gross sales; RFID fee €0.10/item sold; current product-score weights %Sold 0.62 / Margin 0.33 / Review 0.05 (deck targets a 50/50 global/per-fridge dual-score model — pending decision).
- Weekly P&L uses **ADDED (restock) value** as food-cost basis; monthly by-fridge analysis uses **DISPATCHED value** — a deliberate inconsistency in the legacy system; make explicit in any reporting work.
- ~218 products lack `expiryDays` (DLC); ~20 "Box n°" test products must be flagged `is_test`, not deleted.

### Target-stack conventions
- Monorepo: `frontend/` (React + TypeScript + shadcn/ui + Vite), `backend/` (FastAPI + SQLAlchemy 2.0, Python 3.12), `cron/` (Python 3.12 scheduled jobs) — Docker for all three; PostgreSQL (Railway managed) as system of record; blob storage for raw payload archive; deploy on Railway.
- **Frontend charts/graphs use d3.js where possible** (user decision 2026-07-03) — prefer d3 for the React app's visualizations before reaching for chart wrapper libraries. Static HTML mockups stay self-contained (inline SVG standing in for the future d3 charts).
- **No native PG enums in SQLAlchemy** (user decision 2026-07-03): use `native_enum=False` (VARCHAR + CHECK). DB enum columns are being migrated to text+CHECK.
- **Forecast → Menu → Dispatch all key on (iso_year, week_no, day_name)** with import-from-previous-stage, save, load-saved, and explicit overwrite-confirm (delete + reinsert) semantics. Dispatch SAVE = planned (no stock effect); only "create individual dispatch" (is_dispatched) writes stock movements. Stock is always DERIVED from events (`v_stock_balances`), never stored.
- **`dispatch_lines` is range-partitioned by delivery date** (largest projected table), like `sales_events`.
- See `architecture/WORKORDER-workflow-rework.md` for the full 2026-07-03 rework requirements.
- **NO Alembic — explicit decision.** Do not add Alembic (or any migration framework) to the project, do not generate Alembic configs/migrations, and do not recommend it. Schema changes are applied as plain SQL scripts run directly against the database (via `psql` or `psycopg2`), kept under version control.
- **Raw-first ELT rule:** never transform an API payload without archiving the raw response to blob storage first (`raw/husky/{endpoint}/...json.gz`). Sync jobs record every chunk in the `sync_run` table (resumable, auditable).
- **Cron jobs are scheduled by APScheduler** (user decision 2026-07-03): a long-running worker (`python -m cron.scheduler`) in its own Docker container owns all schedules in code. Jobs live in `cron/` and each is ALSO exposed as a plain CLI entry point (`python -m cron.jobs.<name>`) for manual runs and one-off backfills. Do not use Railway cron schedules.
- **Env loading uses python-dotenv explicitly** (user decision 2026-07-03): call `load_dotenv()` on the repo-root `.env` before settings init; `DB_URL` lives there. Never print or commit secrets.
- Deck non-negotiables for later phases: DB-level `CHECK (stock >= 0)`, user+timestamp audit trail on every stock movement, cancel-with-reversal, preserve product ordering on import.
- See `specs/0004-…` (database + historical backfill), specs 0001–0003 (ERP port), and `architecture/system-overview.md` for how the layers link.
