# Backend Layer & Cron Layer Design — Frigoloco Forecasting-Tool Port

## Modification History

| Date (UTC)              | Description      |
|-------------------------|------------------|
| 2026-07-03 (see git)    | Initial creation |
| 2026-07-03 (see git)    | Amended per `FrigoLoco_Dev_Presentation_V5_Final.pptx`: dual scoring model, day-of-week forecast + residual-stock deduction, warehouse stock ledger (§4), dispatch seq / withdrawal / category-order rules, clients / add-on / attachments modules, 4 new cron jobs, five-role model, Railway + Azure Blob infrastructure |

**Parent spec:** `0002-port-forecasting-tool-to-web-app_2026-07-02_0815PM_UTC` (spec part 1: module map, endpoint inventory, table inventory, 7 canonical formulas, vendor sync strategy). This document is the implementation-grade elaboration of the backend and scheduled-job layers. It defines structure, signatures, and algorithms — **not** code. A second authoritative source, the dev briefing **`FrigoLoco_Dev_Presentation_V5_Final.pptx`**, amends the canonical formulas and scope; its changes are integrated inline below and flagged "(v5 briefing)". Where the briefing and legacy Excel behavior diverge (scoring weights, forecast lookback), the briefing wins for production logic and the legacy behavior is retained **only** in Excel-parity tests.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 + Alembic, Pydantic v2, APScheduler, httpx, PostgreSQL 16, WeasyPrint + Jinja2. **Infrastructure (v5 briefing):** hosted on Railway.com; file storage on Azure Blob Storage (§9).

**Coding standards (binding for implementation):** all imports at module top, grouped stdlib / third-party / local; every structured value crossing a function or module boundary is a `@dataclass` or `pydantic.BaseModel` — never a tuple or plain dict; verb-noun function names; `UPPER_SNAKE_CASE` constants; DRY/SOLID (each engine has exactly one reason to change).

---

## 1. Backend project layout

```
backend/
├── pyproject.toml
├── alembic.ini
├── .env.example                      # every setting below, documented
└── app/
    ├── main.py                       # FastAPI app factory, lifespan (starts scheduler), router mounting
    ├── config.py                     # Settings(BaseSettings) via pydantic-settings, reads .env
    ├── api/                          # one router module per domain; thin: parse → call engine/service → respond
    │   ├── deps.py                   # get_db_session, get_current_user, require_roles
    │   ├── auth_router.py            # POST /auth/login, /auth/refresh, GET /auth/me
    │   ├── products_router.py        # GET/PATCH /products, GET /categories
    │   ├── suppliers_router.py       # CRUD /suppliers
    │   ├── fridges_router.py         # GET/PATCH /fridges
    │   ├── forecast_router.py        # /forecast/settings, /forecast/run, /forecast/runs/{id}[/results|/push-to-menu]
    │   ├── scores_router.py          # /scores/weights, /scores/recompute, /scores
    │   ├── menus_router.py           # /menus, /menus/{id}[/products|/allocate|/allocations]
    │   ├── targets_router.py         # /targets, /targets/differences
    │   ├── orders_router.py          # /orders, build-from-menu, confirm, receive, cancel, pdf
    │   ├── stock_router.py           # /stock/position (v_stock_position), /stock/live (cached proxy)
    │   ├── dispatches_router.py      # /dispatches, build-from-menu, copy-from, lines, confirm, notes.zip
    │   ├── verifications_router.py   # /dispatches/{id}/verify, /verifications[/{id}]
    │   ├── reports_router.py         # /reports/weekly, /reports/monthly, /reports/fridge-food-cost, /reports/below-target
    │   ├── clients_router.py         # /clients CRUD, intervention log, preferences, service fees (§4.3)
    │   ├── addons_router.py          # /addon-schedules, /business-lunch-orders (§4.4)
    │   ├── attachments_router.py     # POST/GET /attachments — Azure Blob-backed (§4.5)
    │   ├── admin_router.py           # /settings/fees, /settings/fridge-fees, /users, /audit
    │   └── sync_router.py            # GET /sync/runs, GET /sync/status, POST /sync/run
    ├── engines/                      # pure domain logic; no HTTP, no email; DB via injected session only
    │   ├── forecast_engine.py
    │   ├── scoring_engine.py
    │   ├── allocation_engine.py
    │   ├── verification_engine.py
    │   └── week_utils.py             # ISO-8601 week arithmetic — the only week code in the system
    ├── services/                     # I/O orchestration
    │   ├── vendor_client.py          # IntelligentFridgesClient (httpx)
    │   ├── sync_service.py           # upsert vendor payloads into local tables; sync_runs bookkeeping
    │   ├── stock_service.py          # warehouse stock ledger — sole writer of warehouse_stock/stock_movements (§4.1)
    │   ├── addon_service.py          # recurring add-on schedules → dispatch injection (§4.4)
    │   ├── storage_service.py        # Azure Blob upload/download for attachments (§4.5)
    │   ├── document_service.py       # Jinja2 → HTML → WeasyPrint PDF (PO, dispatch notes, verification report)
    │   └── email_service.py          # SMTP / MS Graph switch; TEST_MODE rerouting
    ├── models/                       # SQLAlchemy 2.0 declarative models, one module per table group
    │   ├── base.py                   # DeclarativeBase, naming conventions, TimestampMixin
    │   ├── masters.py                # Product, ProductCategory, Fridge, Facility, Supplier
    │   ├── telemetry.py              # SalesEvent, RestockEvent, ProductReview, StockSnapshot
    │   ├── forecasting.py            # ForecastSetting, CategoryAdjustment, ForecastRun, ForecastResult
    │   ├── scoring.py                # ScoreWeight, ProductScore
    │   ├── menu.py                   # MenuPlan, MenuProduct, MenuAllocation
    │   ├── ordering.py               # PurchaseOrder, PurchaseOrderLine (+ per-year ref sequences)
    │   ├── dispatch.py               # DispatchPlan (UK week_start_date+day_name+seq — §4.2), DispatchLine, DispatchLineVersion
    │   ├── verification.py           # RestockVerification, VerificationLine
    │   ├── targets.py                # FridgeProductTarget
    │   ├── warehouse.py              # WarehouseStock (CHECK qty >= 0), StockMovement (§4.1)
    │   ├── clients.py                # Client, ClientIntervention, ClientPreference, ClientServiceFee (§4.3)
    │   ├── addons.py                 # AddonServiceSchedule, BusinessLunchOrder (§4.4)
    │   ├── attachments.py            # Attachment — Azure Blob-backed (§4.5)
    │   ├── reporting.py              # WeeklySummary, FeeSetting, FridgeFee, ServiceAdditional
    │   ├── auth.py                   # User, Role
    │   └── ops.py                    # SyncRun, JobRun, AuditLog
    ├── schemas/                      # Pydantic v2 request/response models, mirrors api/ modules 1:1
    │   └── ... (auth.py, products.py, forecast.py, …, common.py for Page[T]/DateWindow/IsoWeek)
    ├── db/
    │   ├── session.py                # async engine, async_sessionmaker, get_db_session dependency
    │   ├── views.sql                 # v_stock_position, v_below_target (applied via Alembic op)
    │   └── migrations/               # Alembic env + versions
    ├── jobs/
    │   ├── scheduler.py              # build_scheduler() → AsyncIOScheduler; register_all_jobs()
    │   ├── job_runner.py             # run_job_with_bookkeeping() — JobRun row, locking, error capture
    │   ├── nightly_incremental_sync_job.py
    │   ├── nightly_score_recompute_job.py
    │   ├── below_target_alert_job.py
    │   ├── weekly_aggregate_cache_job.py
    │   ├── sync_watchdog_job.py
    │   ├── addon_service_dispatch_job.py
    │   ├── expiry_alert_job.py
    │   ├── low_stock_alert_job.py
    │   ├── rfid_offline_alert_job.py
    │   └── backfill_command.py       # one-off CLI: historical 365+ day backfill in monthly chunks
    └── tests/
        ├── engines/                  # golden-file parity tests vs captured Excel outputs
        ├── services/
        ├── api/
        └── jobs/
```

**`config.py` — `Settings(BaseSettings)` fields (env names):** `DATABASE_URL`, `JWT_SECRET_KEY`, `JWT_ACCESS_TTL_MINUTES`, `JWT_REFRESH_TTL_DAYS`, `FRIGOLOCO_IF_BASE_URL`, `FRIGOLOCO_IF_USERNAME`, `FRIGOLOCO_IF_PASSWORD`, `EMAIL_BACKEND` (`smtp` | `msgraph`), `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM_ADDRESS`, `MSGRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET/SENDER`, `TEST_MODE` (bool, default `true` outside production), `TEST_EMAIL_ADDRESS`, `BELOW_TARGET_ALERT_RECIPIENTS`, `OPS_ALERT_RECIPIENTS`, `BELOW_TARGET_CRON` (default `0 7-18 * * 1-5`), `SCHEDULER_TIMEZONE` (default `Europe/Brussels`), `LIVE_STOCK_CACHE_SECONDS` (default `60`), `AZURE_BLOB_CONNECTION_STRING`, `AZURE_BLOB_CONTAINER`, `FORECAST_LOOKBACK_MONTHS` (default `6`, valid 6–12), `EXPIRY_ALERT_DAYS` (default `2`), `RFID_OFFLINE_ALERT_HOURS` (default `6`). One `Settings` instance built at startup and injected — no module reads `os.environ` directly.

**Layering rule:** `api → engines/services → models/db`. Engines never import from `api` or `services`; `services` may call engines; routers contain no business math. This is what keeps each of the 7 canonical formulas (as amended by the v5 briefing) in exactly one tested module.

---

## 2. Engine specifications

All engine inputs/outputs are frozen `@dataclass`es (internal) or Pydantic models (when they surface through the API). Quantities are `int`, money is `Decimal` euros (converted from vendor cents at the client boundary, §3), percentages are `Decimal` fractions (0.10 = 10%).

> **Global exclusion rule (v5 briefing):** products flagged `is_test` are excluded from **every** engine input, score, allocation, dispatch, report aggregate, and alert. Enforced once — a shared query filter in the model layer — never per-caller.

### 2.1 `week_utils.py` — ISO-8601 everywhere

> **Convention decision (intentional legacy change):** every week computation in the system uses **ISO-8601** weeks (weeks start Monday; week 1 contains January 4th). This deliberately replaces the legacy "first Monday of the year" convention used by the weekly ETL (`Add Or Update Weekly Data`), which coexisted with ISO weeks in the dispatch roll-up and could misalign dispatch cost vs sales revenue for the same nominal week. Historical roll-ups are recomputed from event data under the ISO rule at migration time so all periods obey one convention. No other module may implement week arithmetic.

```python
@dataclass(frozen=True)
class IsoWeek:
    iso_year: int
    iso_week: int          # 1..53

@dataclass(frozen=True)
class DateWindow:
    start: date            # inclusive
    end: date              # inclusive

def resolve_iso_week(for_date: date) -> IsoWeek
def resolve_week_start_date(week: IsoWeek) -> date              # the Monday of that ISO week
def resolve_week_window(week: IsoWeek) -> DateWindow            # Monday..Sunday
def resolve_weekday_date(week: IsoWeek, day_name: str) -> date  # "Tuesday" → that week's Tuesday
def build_lookback_windows(anchor_date: date, weeks_back: int) -> list[DateWindow]
    # weeks_back windows of 7 days each, ending the day before anchor_date, aligned so each
    # window starts on the same weekday as (anchor_date - 7*k days) — the "configured start
    # weekday" alignment the Update Forecast script uses for its 3-week lookback
def list_dates_in_window(window: DateWindow) -> list[date]
def prorate_week_days_per_month(week: IsoWeek) -> list[MonthDayShare]
    # MonthDayShare(month: date, day_count: int) — cross-month proration for monthly reports,
    # same day-count rule as the legacy Return workbook
```

### 2.2 `forecast_engine.py` — canonical formula 1, extended per the v5 briefing

The v5 briefing replaces the fixed 3-week lookback with a **day-of-week average over 6–12 months** and adds a **residual-stock deduction** step. The legacy 3-week formula is kept behind a mode flag, used **only** by Excel-parity tests.

```python
SELL_THROUGH_AMBER_THRESHOLD: Final[Decimal] = Decimal("0.90")   # sell-through ≥ 0.90 → amber: risk of under-supply
SELL_THROUGH_RED_THRESHOLD: Final[Decimal] = Decimal("0.70")     # sell-through < 0.70 → red: overfilling
DEFAULT_FORECAST_LOOKBACK_MONTHS: Final[int] = 6                 # configurable 6–12 (FORECAST_LOOKBACK_MONTHS)

ForecastLookbackMode = Literal["day_of_week", "legacy_3_week"]

@dataclass(frozen=True)
class ForecastEngineInput:
    anchor_date: date                       # the dispatch day being planned
    lookback_mode: ForecastLookbackMode     # "day_of_week" in production; "legacy_3_week" for parity tests only
    lookback_months: int                    # day_of_week mode: 6–12 months of history
    weeks_back: int                         # legacy_3_week mode only (default 3)
    coverage_days: int                      # days this delivery must cover (typically days_to_fill; drives the DLC test)
    fridge_settings: list[FridgeForecastSetting]     # per fridge: fridge_id, client_min_qty, days_to_fill, active
    category_adjustments: list[CategoryAdjustment]   # category_id, pct_adjust (Decimal, e.g. 0.10)
    daily_sales: list[DailyCategorySales]   # fridge_id, sale_date, category_id, units_sold (pre-aggregated from sales_events)
    residual_stock: list[ResidualStockUnit] # live fridge contents with per-unit remaining shelf life (DLC)

@dataclass(frozen=True)
class ResidualStockUnit:
    fridge_id: int
    product_id: int
    category_id: int
    quantity: int
    expiry_date: date            # DLC = restock event date + product.shelf_life_days

@dataclass(frozen=True)
class DayClassification:
    sale_date: date
    kind: Literal["valid", "holiday", "no_info"]
    fridge_total_sold: int

@dataclass(frozen=True)
class WeekdayAverage:
    weekday: int                 # 0 = Monday … 6 = Sunday
    avg_units_sold: Decimal      # Mondays averaged with Mondays only

@dataclass(frozen=True)
class CategoryForecast:
    fridge_id: int
    category_id: int
    forecast_qty: Decimal            # gross demand forecast (unrounded; UI rounds for display)
    deductible_residual_qty: int     # residual units with DLC ≥ coverage window (stay in the fridge)
    net_to_deliver_qty: Decimal      # max(0, forecast_qty − deductible_residual_qty)
    total_sold: int
    valid_day_count: int
    holiday_day_count: int
    no_info_day_count: int

@dataclass(frozen=True)
class WithdrawalItem:
    fridge_id: int
    product_id: int
    quantity: int
    expiry_date: date                # DLC < coverage window → pull from the fridge at delivery

@dataclass(frozen=True)
class ResidualStockAssessment:
    deductible: list[ResidualStockUnit]
    withdrawals: list[WithdrawalItem]

@dataclass(frozen=True)
class ForecastEngineOutput:
    results: list[CategoryForecast]
    withdrawal_items: list[WithdrawalItem]               # rendered on the dispatch note PDF (§6.1)
    day_classifications: list[FridgeDayClassification]   # fridge_id + DayClassification, for tooltips/audit

class WeatherAdjustmentProvider(Protocol):
    # Phase 5 placeholder — 18-month weather/sales correlation model. The v1 implementation
    # (NoOpWeatherAdjustmentProvider) always returns Decimal("1.0"). NOT v1 logic; hook only.
    def resolve_weather_factor(self, fridge_id: int, category_id: int, target_date: date) -> Decimal

def compute_category_forecasts(engine_input: ForecastEngineInput,
                               weather_provider: WeatherAdjustmentProvider) -> ForecastEngineOutput
def classify_fridge_days(fridge_id: int, window: DateWindow,
                         daily_sales: list[DailyCategorySales],
                         client_min_qty: int) -> list[DayClassification]
def build_day_of_week_averages(fridge_id: int, category_id: int,
                               daily_sales: list[DailyCategorySales],
                               classifications: list[DayClassification]) -> list[WeekdayAverage]
def assess_residual_stock(residual_stock: list[ResidualStockUnit], coverage_days: int,
                          as_of: date) -> ResidualStockAssessment
```

**Algorithm — `day_of_week` mode (production):**

1. **Lookback window** = `lookback_months` calendar months ending the day before `anchor_date` (configurable 6–12).
2. **Day classification** (unchanged edge rules, per fridge, using the fridge's **total units sold across all categories** that day):
   - **no_info** — no sales data at all for that fridge/date (offline or data gap). *Counts in the denominator.*
   - **holiday** — data exists but `fridge_total_sold <= client_min_qty` (automatic holiday exclusion: near-zero-sales days). *Excluded entirely.* Edge rule is `<=`, not `<`: a day selling exactly the minimum is still a holiday.
   - **valid** — otherwise.
3. **Per fridge × category × weekday:** `avg_units_sold(weekday) = Σ sold on valid same-weekday days / (valid + no_info same-weekday day count)` — Mondays are averaged with Mondays only. Denominator `0` → average `0`.
4. **Gross forecast** = `Σ over each calendar day d in the coverage window (anchor_date .. anchor_date + coverage_days − 1) of avg_units_sold(weekday(d))`, then `× (1 + pct_adjust)` `× weather_factor` (v1: always `1.0`; the provider hook exists so Phase 5 plugs in without touching the engine).
5. **Residual stock deduction (new step):** the service pulls live fridge stock and computes each unit's DLC (`restock event date + shelf_life_days`). `assess_residual_stock` partitions units: `expiry_date − as_of >= coverage_days` → **deductible** (product stays in the fridge and offsets demand); otherwise → **withdrawal list** (to be pulled at delivery). Per fridge × category: `net_to_deliver_qty = max(0, forecast_qty − deductible_residual_qty)`. **The allocation engine consumes `net_to_deliver_qty`, not the gross forecast.** Units of products with `shelf_life_days IS NULL` cannot be assessed — those products are blocked from dispatch anyway (§4.1).
6. Categories 6 (Snacks) and 7 (Drinks) are still computed and stored, but the allocation engine ignores them (they are target-driven, §2.4).
7. **Persistence:** a `forecast_runs` row + one `forecast_results` row per fridge × category (incl. day counts, residual and net quantities) + `forecast_withdrawals` rows for the withdrawal list. Runs are never overwritten — each `POST /forecast/run` creates a new run. The UI tooltip still reads "based on N valid days (M excluded as closed)".
8. **Sell-through diagnostics:** per fridge × category, `sell_through = sold / added` for the last completed week is returned with the run; the API exposes `SELL_THROUGH_AMBER_THRESHOLD` / `SELL_THROUGH_RED_THRESHOLD` so the SPA colors cells: ratio ≥ 0.90 amber (likely under-supplied), < 0.70 red (overfilling). Thresholds are constants server-side — the UI never hardcodes them.

**Algorithm — `legacy_3_week` mode (Excel-parity tests only):** the original canonical formula, unchanged: `build_lookback_windows(anchor_date, weeks_back)` (`weeks_back × 7` days aligned to the anchor weekday); same day classification; `forecast_qty = (total_sold_for_category / (valid_day_count + no_info_day_count)) × days_to_fill × (1 + pct_adjust)`; `denominator == 0` → `0`. No residual deduction, no weather factor — it must reproduce the captured Excel outputs bit-for-bit.

### 2.3 `scoring_engine.py` — canonical formula 2, **replaced** by the v5 dual-score model

The v5 briefing replaces the single global 0.62/0.33/0.05 score with a **dual model**: a global score, a per-fridge score (margin deliberately excluded — margin is a property of the product, not of where it sells), and a 50/50 combination. **The legacy Excel weights (0.62/0.33/0.05) survive only as `LEGACY_EXCEL_SCORE_WEIGHTS` in the parity-test suite**, validating the component formulas against historical `Update Rating` outputs.

```python
COMBINED_GLOBAL_SHARE: Final[Decimal] = Decimal("0.5")            # combined = 0.5·global + 0.5·fridge
NEW_PRODUCT_LIFETIME_SALES_THRESHOLD: Final[int] = 250
DEFAULT_GLOBAL_SCORE_WEIGHTS: Final[GlobalScoreWeights]  # sold 0.55 · margin 0.30 · review 0.15
DEFAULT_FRIDGE_SCORE_WEIGHTS: Final[FridgeScoreWeights]  # sold 0.70 · review 0.30 (no margin term)
LEGACY_EXCEL_SCORE_WEIGHTS: Final[GlobalScoreWeights]    # 0.62/0.33/0.05 — parity tests ONLY, never production

@dataclass(frozen=True)
class GlobalScoreWeights:
    sold_weight: Decimal      # default 0.55
    margin_weight: Decimal    # default 0.30
    review_weight: Decimal    # default 0.15
    # user-editable; PUT /scores/weights validates sold+margin+review == 1.00 exactly

@dataclass(frozen=True)
class FridgeScoreWeights:
    sold_weight: Decimal      # default 0.70
    review_weight: Decimal    # default 0.30 — margin deliberately excluded per-fridge
    # user-editable; must sum to 1.00 exactly

@dataclass(frozen=True)
class ProductScoreInput:
    product_id: int
    sold_qty: int             # Σ sales_events in window (refunded sales excluded)
    added_qty: int            # Σ reliable restock ADDED events in window (UNRELIABLE excluded)
    lifetime_sold_qty: int    # all-time sales count — drives the new-product placeholder rule
    positive_reviews: int     # rating == 1
    negative_reviews: int     # rating != 1
    purchase_price: Decimal   # buy price ("reference")
    sales_price_ex_vat: Decimal

@dataclass(frozen=True)
class FridgeScoreInput:
    product_id: int
    fridge_id: int
    fridge_sold_qty: int      # same window, scoped to this fridge
    fridge_added_qty: int
    fridge_positive_reviews: int
    fridge_negative_reviews: int

@dataclass(frozen=True)
class FridgeScore:
    fridge_id: int
    fridge_sold_pct: Decimal
    fridge_review_pct: Decimal
    fridge_score: Decimal     # 0.70·fridge_sold_pct + 0.30·fridge_review_pct
    combined_score: Decimal   # 0.5·global_score + 0.5·fridge_score — what allocation consumes

@dataclass(frozen=True)
class ProductScoreResult:
    product_id: int
    window: DateWindow
    sold_pct: Decimal
    margin_pct: Decimal
    review_pct: Decimal
    global_score: Decimal
    fridge_scores: list[FridgeScore]
    is_new_product_placeholder: bool   # True when lifetime_sold_qty <= 250

def compute_global_product_score(score_input: ProductScoreInput,
                                 weights: GlobalScoreWeights) -> Decimal
def compute_fridge_scores(fridge_inputs: list[FridgeScoreInput], weights: FridgeScoreWeights,
                          global_score: Decimal) -> list[FridgeScore]
def compute_all_product_scores(score_inputs: list[ProductScoreInput],
                               fridge_inputs: list[FridgeScoreInput],
                               global_weights: GlobalScoreWeights,
                               fridge_weights: FridgeScoreWeights,
                               window: DateWindow) -> list[ProductScoreResult]
```

**Algorithm** (365-day trailing window):

- **Component definitions (shared by global and fridge scopes, same edge rules as legacy):**
  - `sold_pct = sold_qty / added_qty`; if `added_qty == 0` → `0`. Not clamped — a value > 1 (sold more than reliably added) is preserved.
  - `margin_pct = (sales_price_ex_vat − purchase_price) / sales_price_ex_vat`; if `sales_price_ex_vat == 0` → `0`.
  - `review_pct = (positive − negative) / (positive + negative)`; if no reviews → `0`.
- **Global score** = `0.55 × sold_pct + 0.30 × margin_pct + 0.15 × review_pct` (weights editable via `PUT /scores/weights`).
- **Per-fridge score** = `0.70 × fridge_sold_pct + 0.30 × fridge_review_pct`, computed from fridge-scoped sales/restocks/reviews. **No margin term per-fridge, by design.**
- **Combined score** (per product × fridge) = `0.5 × global_score + 0.5 × fridge_score`. This is the number the allocation engine consumes for the fridge being allocated.
- **New-product rule:** a product with `lifetime_sold_qty <= NEW_PRODUCT_LIFETIME_SALES_THRESHOLD` (250) takes the **average global score of all established products** as its global score placeholder; fridge scoring is skipped and `combined_score = global_score` for every fridge; `is_new_product_placeholder = True` so the UI can badge it.
- Inputs come from **local** `sales_events` / `restock_events` / `product_reviews` tables (the nightly sync keeps them current) — never a live 12×-monthly API pull as the Excel script did. UNRELIABLE-status restock tags are excluded from `added_qty` exactly as they are separated in verification (§2.5).
- **Persistence:** `product_scores` (global components + score, placeholder flag, window, `computed_at`) plus `product_fridge_scores` (product, fridge, fridge components, fridge score, combined score). Menu Planner pickers sort by **global** score; the allocation engine reads the **combined** score for the target fridge — still one number per decision, in one place.

### 2.4 `allocation_engine.py` — canonical formulas 3 & 4

```python
ALLOCATION_BUMP_QTY: Final[Decimal] = Decimal("0.51")
ALLOCATION_BUMP_THRESHOLD: Final[Decimal] = Decimal("0.5")
TARGET_DRIVEN_CATEGORY_CODES: Final[frozenset[int]] = frozenset({6, 7})   # Snacks, Drinks

@dataclass(frozen=True)
class ScoredMenuProduct:
    product_id: int
    final_score: Decimal          # v5: the COMBINED per-fridge score (§2.3) resolved when allocation
                                  # runs; menu_products snapshots the global score for display only

@dataclass(frozen=True)
class CategoryAllocationInput:
    fridge_id: int
    category_id: int
    forecast_qty: Decimal          # v5: net_to_deliver_qty from the pushed forecast run (residual already deducted, §2.2)
    products: list[ScoredMenuProduct]

@dataclass(frozen=True)
class ProductAllocation:
    fridge_id: int
    category_id: int
    product_id: int
    quantity: int                  # final rounded units
    source: Literal["engine"]      # manual edits are written by the router, never by the engine

def allocate_category_for_fridge(allocation_input: CategoryAllocationInput) -> list[ProductAllocation]
def allocate_menu_plan(allocation_inputs: list[CategoryAllocationInput],
                       preserved_manual_allocations: list[ManualAllocationKey]) -> list[ProductAllocation]
    # ManualAllocationKey(fridge_id, category_id, product_id) — cells the engine must not touch
    # unless the caller passed reset_overrides=True (then the list is empty)
```

**Menu allocation algorithm** (per fridge × category, exact port of `Update Menu`):

1. Skip categories in `TARGET_DRIVEN_CATEGORY_CODES` — they are filled by replenishment (below), not by score split.
2. `score_sum = Σ final_score` over the category's selected products. If `score_sum == 0` or `forecast_qty <= 0`, every product gets `0`.
3. Iterate products **in descending score order**, tracking `remaining = forecast_qty`:
   a. `raw = forecast_qty × final_score / score_sum`; a product with `final_score == 0` gets `0` — never bumped.
   b. **Cap:** `raw = min(raw, remaining)`.
   c. **The 0.51 bump:** if `remaining > ALLOCATION_BUMP_THRESHOLD` and `raw < ALLOCATION_BUMP_THRESHOLD`, set `raw = ALLOCATION_BUMP_QTY` — guarantees real residual demand rounds up to at least 1 unit instead of vanishing to 0.
   d. `quantity = round(raw)` (banker's rounding OFF — use `ROUND_HALF_UP` to match Excel's `Math.round`); `remaining -= quantity` (floored at 0).
4. **Leftover rule:** after the pass, if `remaining` rounds to ≥ 1 unit, add `round(remaining)` to the **highest-scored** product's quantity.
5. Manual cells (`source = "manual"` in `menu_allocations`) are excluded from recomputation and their quantities subtracted from `forecast_qty` before the split, unless the caller requested `reset_overrides`.

**Snacks/Drinks replenishment** (exact port of `Refresh Drinks And Snacks`):

```python
@dataclass(frozen=True)
class ReplenishmentDifference:
    fridge_id: int
    product_id: int
    target_qty: int
    current_live_stock: int
    difference: int            # target_qty − current_live_stock; may be negative (overstocked)

def compute_replenishment_differences(targets: list[FridgeProductTargetInput],
                                      live_stock: list[LiveStockCount]) -> list[ReplenishmentDifference]
```

`difference = target_qty − current_live_stock` per fridge × product; missing live-stock entry means `current_live_stock = 0`. This single function feeds the Targets screen, the Menu Planner's read-only snack/drink columns, and the `v_below_target` alert view semantics (below target ⇔ `difference > 0`).

### 2.5 `verification_engine.py` — canonical formula 7

```python
UNRELIABLE_TAG_STATUS: Final[str] = "UNRELIABLE"

@dataclass(frozen=True)
class DispatchedLineInput:
    fridge_id: int
    product_id: int
    dispatched_qty: int
    purchase_price_snapshot: Decimal    # price at dispatch confirmation, not current price

@dataclass(frozen=True)
class RestockEventInput:
    fridge_id: int
    product_id: int
    tag_id: str
    tag_status: str

@dataclass(frozen=True)
class VerificationDiffLine:
    fridge_id: int
    product_id: int
    dispatched_qty: int
    added_qty: int              # reliable tags only
    unreliable_qty: int         # counted separately, never in added_qty
    diff_qty: int               # added_qty − dispatched_qty
    diff_value: Decimal         # diff_qty × purchase_price_snapshot

@dataclass(frozen=True)
class VerificationSummary:
    lines: list[VerificationDiffLine]           # every fridge × product touched by either side
    discrepancy_lines: list[VerificationDiffLine]  # diff_qty != 0 or unreliable_qty > 0
    total_diff_value: Decimal
    total_unreliable_qty: int

def compute_restock_verification(dispatched_lines: list[DispatchedLineInput],
                                 restock_events: list[RestockEventInput]) -> VerificationSummary
```

**Algorithm** (exact port of `Send Restock Verification Alert`): group restock events by fridge × product; one RFID tag = one unit; tags with `tag_status == UNRELIABLE_TAG_STATUS` increment `unreliable_qty` only and are **excluded** from `added_qty`. Union the key set from both dispatched lines and restock events (a restocked product that was never dispatched still appears, with `dispatched_qty = 0`; a dispatched product never scanned appears with `added_qty = 0`). `diff_qty = added_qty − dispatched_qty`; `diff_value = diff_qty × purchase_price_snapshot` (product's current purchase price when no snapshot exists, e.g. never-dispatched keys). The service layer syncs that dispatch date's restock window from the vendor **before** calling the engine, persists a `restock_verifications` + `verification_lines` row set, and emails the alert only when `discrepancy_lines` is non-empty.

### 2.6 Formulas owned outside the engines (for completeness)

- **Stock position (formula 5)** lives in the SQL view `v_stock_position`, never in Python and never as a stored table:
  `currently_in_stock_and_ordered = pending_to_receive + received − dispatched`, where `pending_to_receive` = Σ `qty_ordered` of lines on `status = 'sent'|'partially_received'` orders (their un-received remainder), `received` = Σ `qty_received` on non-cancelled orders, `dispatched` = Σ `dispatch_lines.quantity` where `is_dispatched = true`. Cancelled orders contribute nothing. **(v5 amendment)** The physically **enforced** warehouse ledger is `warehouse_stock` (§4.1); `v_stock_position` is retained as the derived reconciliation view — a drift check between ledger and documents, and the parity artifact for the legacy Stock & Ordered sheet.
- **Order reference (formula 6)** lives in the ordering model layer: `order_ref = f"{year}-{sequence:05d}"` from a **per-year PostgreSQL sequence** (created on first use inside the confirm transaction). Race-safe by construction, unlike the legacy max+1 sheet scan; assigned only at `POST /orders/{id}/confirm`, drafts have no ref.

---

## 3. Vendor API client — `services/vendor_client.py`

One class, `IntelligentFridgesClient`, wrapping `httpx.AsyncClient` with `base_url = FRIGOLOCO_IF_BASE_URL` and `auth = httpx.BasicAuth(FRIGOLOCO_IF_USERNAME, FRIGOLOCO_IF_PASSWORD)` from `Settings`. **Credentials exist only in environment configuration** (the legacy plaintext-in-script credentials are retired and the vendor password rotated at cutover).

```python
VENDOR_MAX_RETRIES: Final[int] = 4
VENDOR_BACKOFF_BASE_SECONDS: Final[float] = 1.0     # 1, 2, 4, 8 + jitter
VENDOR_REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0
RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})

class IntelligentFridgesClient:
    async def fetch_purchases(self, window: DateWindow) -> list[VendorPurchase]
    async def fetch_restock_events(self, window: DateWindow,
                                   action: str = "ADDED") -> list[VendorRestockEvent]
    async def fetch_current_stock(self) -> list[VendorStockEntry]
    async def fetch_product_types(self) -> list[VendorProductType]
    async def fetch_product_reviews(self, window: DateWindow) -> list[VendorProductReview]
    async def fetch_facilities(self) -> list[VendorFacility]
```

**Typed response models** (Pydantic v2, one per endpoint; field names/paths finalized against `specs/0001-…/reference-docs/intelligentfridges_openapi_v1.json`):

| Model | Endpoint | Key fields (normalized) |
|---|---|---|
| `VendorPurchase` | `GET /purchases?from&to` | `tag_id` (natural key), `fridge_code`, `product_code`, `sold_at: datetime`, `unit_price: Decimal €`, `vat_rate`, `refund_status`, `discount_provider`, `discount_amount: Decimal €` |
| `VendorRestockEvent` | `GET /restock?from&to&action=ADDED` | `tag_id`, `fridge_code`, `product_code`, `event_at: datetime`, `action`, `tag_status` (may be `UNRELIABLE`) |
| `VendorStockEntry` | `GET /stock/current` | `fridge_code`, `product_code`, `live_tag_count: int` |
| `VendorProductType` | `GET /producttype` | `product_code`, `name`, `category_code`, `brand` (= supplier name), `purchase_price: Decimal €` (vendor field `reference`), `sales_price: Decimal €`, `vat_rate`, `expiry_days` |
| `VendorProductReview` | `GET /productreview?from&to` | `product_code`, `rating: int` (`1` counts positive, anything else negative), `reviewed_at` |
| `VendorFacility` | `GET /facility` | `facility_code`, `name`, `delivery_address`, `delivery_instructions`, `contact_email` |

**Boundary rules:**

- **Prices-in-cents normalization happens here and nowhere else.** Every vendor money field is an integer number of cents; each model normalizes it with a field validator to `Decimal` euros (`cents / 100`). No cent value ever crosses into engines, services, or the DB.
- **Retry:** each request retries up to `VENDOR_MAX_RETRIES` on `httpx.TransportError`, timeouts, and `RETRYABLE_STATUS_CODES`, sleeping `VENDOR_BACKOFF_BASE_SECONDS × 2^attempt` plus 0–0.5 s jitter; `429` honors `Retry-After` when present. Non-retryable 4xx raises `VendorApiError(BaseModel: status_code, endpoint, detail)` immediately.
- **Windows:** all windowed fetches take a `DateWindow` (from `week_utils`) — callers never format `from`/`to` query strings themselves.
- Client is created once in the FastAPI lifespan and shared (connection pooling); `sync_service.py` and the on-demand `/stock/live` proxy are its only consumers.

`sync_service.py` exposes one verb per target: `sync_purchases(window)`, `sync_restock_events(window)`, `sync_product_reviews(window)`, `sync_product_catalog()`, `sync_facilities()`, `capture_stock_snapshot()`. Each fetches via the client, **upserts idempotently** (`INSERT … ON CONFLICT` on the natural key: `tag_id` for sales/restock events, `product_code`, `facility_code`, review natural key), never overwrites local-override columns on masters (`active`, display name, delivery-instructions override), and writes exactly one `sync_runs` row (`endpoint, window_from, window_to, status, rows_fetched, rows_inserted, rows_updated, error, started_at, finished_at`). Every sync function returns a `SyncOutcome(BaseModel)` — never a bare count or dict.

---

## 4. Warehouse stock & new domain modules (v5 briefing)

### 4.1 `services/stock_service.py` — warehouse stock ledger

The warehouse now has a **physically enforced** stock ledger. `stock_service` is the **sole writer** of both tables — no router or job mutates them directly (Single Responsibility; DRY).

**Tables:** `warehouse_stock` (`product_id` UK, `qty int` with **DB constraint `CHECK (qty >= 0)`**) and `stock_movements` (`product_id`, `delta`, `movement_type`: `po_receipt | dispatch_deduct | dispatch_reversal | order_cancel_reversal | manual_adjustment | addon_dispatch_deduct`, `reason` (mandatory for manual adjustments), `user_id`, `related_entity_type`, `related_entity_id`, `occurred_at`). Every movement carries user + timestamp — full traceability.

```python
@dataclass(frozen=True)
class StockDeductionRequest:
    product_id: int
    quantity: int
    related_entity_type: str
    related_entity_id: int

class StockAvailabilityCheck(BaseModel):
    is_available: bool
    shortfalls: list[StockShortfall]      # StockShortfall(product_id, requested_qty, available_qty)

class StockMovementResult(BaseModel):
    movements: list[RecordedStockMovement]

def check_stock_availability(deductions: list[StockDeductionRequest]) -> StockAvailabilityCheck
def record_purchase_order_receipt(order_id: int, received_lines: list[ReceivedLineInput],
                                  user_id: int) -> StockMovementResult
def deduct_stock_for_dispatch_save(plan_id: int, line_diffs: list[StockDeductionRequest],
                                   user_id: int) -> StockMovementResult
def reverse_stock_for_order_cancellation(order_id: int, user_id: int) -> StockMovementResult
def apply_manual_stock_adjustment(product_id: int, delta: int, reason: str,
                                  user_id: int) -> StockMovementResult
```

**Rules:**

- **Negative stock is blocked before the fact, not detected after.** `check_stock_availability` runs **before** any operation that would deduct; a shortfall aborts the operation with a 409 + typed shortfall detail **and** sends an ops alert email. The DB `CHECK (qty >= 0)` is the backstop against races. This is deliberately **not** a cron job (§5).
- **Every PO receipt adds stock; every dispatch save deducts** (diff-based: grid saves deduct/return only the delta per product); **order cancellation runs an explicit cancel-with-reversal** (`reverse_stock_for_order_cancellation`), never a silent status flip.
- **Manual adjustments require a non-empty `reason`** — validated at schema level.
- **NULL shelf-life dispatch block:** 218 products are missing DLC (`shelf_life_days IS NULL`) at migration. Dispatch line save/confirm **rejects** those products with an actionable error naming them; the Admin products screen is where DLC gets filled in.

### 4.2 Dispatch-layer amendments

- **Two dispatches per day:** `dispatch_plans` unique key becomes (`week_start_date`, `day_name`, `seq`), `seq` starting at 1. All plan lookups and the Dispatch Board picker are seq-aware.
- **Past-date guard:** saving or confirming a plan whose dispatch date is in the past requires an explicit `confirm_past_date: bool = true` in the request body; otherwise 422 with an explanatory message.
- **Dispatch sheet category order** is a constant, used by the dispatch-note PDF and the board's column-group ordering:
  `DISPATCH_SHEET_CATEGORY_ORDER: Final[tuple[str, ...]] = ("Hot", "Frozen", "Salads", "Wraps", "Granolas", "Soups", "Desserts", "Drinks", "Snacks")`
- **Withdrawal list on the note:** each fridge's dispatch-note PDF renders that fridge's `WithdrawalItem`s (§2.2) as a "to remove" section (§6.1).
- **Printed reminders:** free-text reminder lines (e.g. « N'oubliez pas votre uniforme ») configurable per sheet — a `dispatch_note_reminders` setting with a global default and per-fridge/per-plan override.

### 4.3 Clients module — `clients_router.py` + `models/clients.py`

CRUD for client companies behind the fridges: `Client` (name, contact, `workers_count`, `workers_type`, linked fridges), `ClientServiceFee` (fee type, amount, period), `ClientPreference` (free-form keyed preferences), `ClientIntervention` (dated log: kind, note, `user_id` — the on-site intervention history). Endpoints: `GET/POST/PATCH /clients`, `GET/POST /clients/{id}/interventions`, `GET/PUT /clients/{id}/preferences`, `GET/PUT /clients/{id}/fees`. Thin CRUD — no service module needed.

### 4.4 Add-on services — `addons_router.py` + `services/addon_service.py`

- `AddonServiceSchedule` (client/fridge, item description or `product_id`, quantity — e.g. "5 kg fruit" —, recurrence weekdays such as Mon+Wed, `exclude_holidays: bool`, active date range). `BusinessLunchOrder` (client, date, lines, status) for one-off catering orders.
- `addon_service.resolve_due_addon_items(target_date: date) -> list[DueAddonItem]` applies weekday matching and the holiday exclusion (against the configured holiday calendar).
- The `addon_service_dispatch` cron job (§5) injects due items into that day's dispatch plan automatically.

### 4.5 Attachments — `attachments_router.py` + `services/storage_service.py`

- Azure Blob Storage behind a small service: `upload_attachment(entity_type, entity_id, filename, content_type, content_bytes, user_id) -> StoredAttachment(BaseModel: attachment_id, blob_path, download_url)` and `build_attachment_download_url(attachment_id) -> str` (time-limited SAS URL). Connection settings from `AZURE_BLOB_CONNECTION_STRING` / `AZURE_BLOB_CONTAINER`.
- Table `attachments` (`entity_type`, `entity_id`, `blob_path`, `filename`, `content_type`, `uploaded_by`, `uploaded_at`).
- **Primary v1 use case:** scanned supplier delivery notes attached to PO receipts — `POST /orders/{id}/receive` accepts attachment references so the paper trail lives next to the receipt. (This is also the raw material for the deferred Peppol 3-way reconciliation, §9.)

---

## 5. Cron layer — `jobs/`

`AsyncIOScheduler` (timezone `SCHEDULER_TIMEZONE`, default Europe/Brussels) is built in `jobs/scheduler.py` and started/stopped inside the FastAPI **lifespan** context in `main.py` — same process, same event loop, same session factory as the API. Every job is a thin async function that delegates to `job_runner.run_job_with_bookkeeping(job_name, job_callable)`, which:

1. Takes a PostgreSQL advisory lock keyed on `job_name` — a manual trigger and the schedule can never run the same job concurrently; the loser exits immediately with status `skipped_locked`.
2. Inserts a `job_runs` row (`job_name, trigger: scheduled|manual, status, started_at, finished_at, detail JSONB, error`), updating it on completion. Sync-flavoured jobs additionally produce their per-endpoint `sync_runs` rows via `sync_service`.
3. Catches all exceptions, records them, and never kills the scheduler.

**Manual re-run:** `POST /sync/run` (admin / ops_manager roles) accepts `JobTriggerRequest(BaseModel: job_name, window: DateWindow | None)` and invokes the identical job callable with `trigger="manual"`. Because every job is idempotent (below), re-running manually after a failure — or twice in a row — is always safe.

| Job | Schedule | Inputs | Idempotency strategy | Failure handling | Writes |
|---|---|---|---|---|---|
| `nightly_incremental_sync` | 02:00 daily | Trailing-3-day `DateWindow` (today−3 .. today), or the override window from a manual trigger | Upserts on natural keys (`tag_id`, `product_code`, `facility_code`); the 3-day overlap re-captures late-arriving events; re-runs converge to the same rows | Per-endpoint isolation: a purchases failure does not block restock/catalog sync; each endpoint gets its own `sync_runs` row; job status = `partial_failure` if any endpoint failed (watchdog picks it up) | `sales_events`, `restock_events`, `product_reviews`, `products`, `product_categories`, `fridges`, `facilities`, `sync_runs`, `job_runs` |
| `nightly_score_recompute` | 03:00 daily (after sync) | 365-day trailing `DateWindow`; current `score_weights` row; reads **local** telemetry tables only — zero vendor calls | Inserts a fresh `product_scores` batch keyed by (`product_id`, `computed_at`); "latest per product" is a query, so duplicate runs are harmless history | Whole-batch transaction: all products or none; on failure the previous night's scores remain current and menus stay usable | `product_scores`, `job_runs` |
| `below_target_alert` | `BELOW_TARGET_CRON` env cron, default hourly 07:00–18:00 Mon–Fri | `v_below_target` (targets vs latest stock snapshot; `capture_stock_snapshot()` refreshes it first); `BELOW_TARGET_ALERT_RECIPIENTS` | Send-once guard: a hash of the below-target row set is stored in the `job_runs.detail`; identical consecutive result sets do not re-email. No rows → no email, status `no_findings` | Email failure marks the run failed but does not retry within the run (next hourly tick is the retry); stock-snapshot failure falls back to the previous snapshot with a staleness note in the email | `stock_snapshots`, `job_runs`; outbound HTML-table email (port of `Get Below Target Items`, rendered by `email_service` from a Jinja2 template) |
| `weekly_aggregate_cache` | Monday 04:00 | The just-completed ISO week (`resolve_iso_week(today − 7 days)`); local `sales_events`, `restock_events`, `dispatch_lines` | Upsert on `weekly_summaries(iso_year, iso_week)` — **only the API-aggregate columns**; manual-input columns (catering turnover, TGTG, logistics cost, drops, unsold, remarks) are never touched by the job | On failure the weekly report endpoint computes aggregates on the fly (slower, still correct) — the cache is an optimization, not a source of truth | `weekly_summaries` (aggregate columns), `job_runs` |
| `sync_watchdog` | 06:00 daily + every 6 h | `sync_runs` + `job_runs` since the last watchdog run; `OPS_ALERT_RECIPIENTS` | Alerts reference the specific failed run ids in `job_runs.detail`; already-alerted run ids are skipped on the next pass | The watchdog itself failing is visible on the Admin sync screen (`GET /sync/status` flags "watchdog silent > 24 h") | `job_runs`; outbound ops-alert email listing failed/partial runs and endpoints stale > 48 h |
| `addon_service_dispatch` (v5) | 05:30 daily | `addon_service.resolve_due_addon_items(today)` — active schedules matching today's weekday, minus holiday-excluded ones (§4.4) | Injected lines carry `source = addon` + the schedule id; upsert per (plan, schedule_id) — re-runs never duplicate a line. Creates the day's draft `dispatch_plans` row (seq 1) if none exists | Per-schedule isolation: one bad schedule is recorded in `job_runs.detail` and skipped; watchdog surfaces the partial failure | `dispatch_plans` (draft, if created), `dispatch_lines` (source = addon), `job_runs` |
| `expiry_alert` (v5) | 07:00 daily | Live-stock snapshot + per-unit DLC (restock date + `shelf_life_days`); threshold `EXPIRY_ALERT_DAYS` (default 2, configurable) | Send-once guard: hash of the expiring (fridge, product, expiry_date) set in `job_runs.detail`; unchanged set → no re-email. Empty set → status `no_findings` | Snapshot-refresh failure falls back to the latest stored snapshot with a staleness note in the email | `stock_snapshots`, `job_runs`; email listing products in fridges expiring within N days |
| `low_stock_alert` (v5) | 07:30 daily | `warehouse_stock` vs per-product `minimum_stock_qty` (configurable per product on the Admin products screen; NULL = no alerting) | Same hash-based send-once guard as `expiry_alert` | Pure local read — only email delivery can fail; next run retries | `job_runs`; email listing products at/below their configured minimum |
| `rfid_offline_alert` (v5) | hourly | Fridges with **zero** `sales_events` in the last `RFID_OFFLINE_ALERT_HOURS` (configurable, default 6) | A fridge is alerted once per outage: alerted fridge ids are held in `job_runs.detail` and suppressed until a sale is seen again (recovery resets the guard) | Pure local read; email failure retried on the next hourly tick | `job_runs`; ops email naming the silent fridges and their last-sale timestamps |

> **Negative warehouse stock is deliberately not a cron.** It is prevented before the fact by `stock_service.check_stock_availability` and enforced by the `CHECK (qty >= 0)` DB constraint (§4.1); the ops alert fires at block time, synchronously — a scheduled scan would only ever find what the constraint already made impossible.

**Historical backfill** is deliberately *not* a scheduled job: `jobs/backfill_command.py` is a CLI (`python -m app.jobs.backfill_command --from 2025-07-01 --to 2026-07-01`) that pulls purchases/restock/reviews in **monthly chunks** (mirroring what `Update Rating` did per click), writing one `sync_runs` row per chunk so an interrupted backfill **resumes from the last successful chunk**. Row counts are verified against the legacy Update Rating totals as the parity check named in the parent spec's risk table.

---

## 6. Document & email service

### 6.1 `document_service.py`

WeasyPrint renders HTML → PDF; Jinja2 (autoescape on, `StrictUndefined` so a missing field fails loudly in tests rather than printing blank on a supplier document) produces the HTML. Templates live in `app/services/templates/` and **mirror the three legacy template workbooks' layouts**:

| Function | Template (mirrors) | Context model | Output |
|---|---|---|---|
| `render_purchase_order_pdf(order: PurchaseOrderDocumentContext) -> RenderedDocument` | `purchase_order.html` (POTemplate: supplier block, order ref, order/delivery dates, delivery address, comment, line table with code/name/buy €/VAT/qty/line total, totals ex-VAT / VAT / inc-VAT) | `PurchaseOrderDocumentContext(BaseModel)` | one PDF |
| `render_dispatch_note_pdfs(dispatch: DispatchNotesDocumentContext) -> list[RenderedDocument]` | `dispatch_note.html` (DispatchTemplate: **one PDF per fridge** — the ~42-sheet workbook becomes ~42 PDFs — delivery date, facility address + instructions from the facility sync, product/qty lines grouped **in `DISPATCH_SHEET_CATEGORY_ORDER`**: Hot → Frozen → Salads → Wraps → Granolas → Soups → Desserts → Drinks → Snacks (§4.2); a **withdrawal list** section for that fridge's `WithdrawalItem`s (§2.2); configurable printed reminder lines, e.g. « N'oubliez pas votre uniforme » (§4.2)) | `DispatchNotesDocumentContext(BaseModel)` | one PDF per fridge, plus `build_dispatch_notes_zip()` for `GET /dispatches/{id}/notes.zip` |
| `render_restock_verification_pdf(verification: VerificationDocumentContext) -> RenderedDocument` | `restock_verification.html` (RestockVerificationTemplate: category summary strip, fridge-grouped diff lines with dispatched/added/unreliable/Δqty/Δ€) | `VerificationDocumentContext(BaseModel)` | one PDF |

`RenderedDocument(BaseModel: filename, content_type, content_bytes)` is the single return type; PDFs are stored on the owning row (or object storage path) so `GET /orders/{id}/pdf` re-serves the **exact** document that was emailed, not a re-render at current prices.

### 6.2 `email_service.py`

```python
class OutboundEmail(BaseModel):
    recipients: list[EmailStr]
    cc: list[EmailStr] = []
    subject: str
    html_body: str
    attachments: list[RenderedDocument] = []

class EmailDispatchResult(BaseModel):
    delivered_to: list[EmailStr]        # actual recipients after TEST_MODE rerouting
    rerouted_by_test_mode: bool
    backend: Literal["smtp", "msgraph"]

async def send_email(email: OutboundEmail) -> EmailDispatchResult
```

- **Backend switch:** `EMAIL_BACKEND` selects an SMTP implementation (aiosmtplib) or MS Graph `sendMail` (httpx, client-credentials token) behind one `EmailBackend` protocol — config-switchable, no caller changes (Dependency Inversion).
- **TEST_MODE (port of `OrderSheetIsTestRun`), global and unconditional:** when `TEST_MODE=true`, **every** outbound email — supplier POs, dispatch notes, restock alerts, below-target alerts, watchdog alerts — is rerouted to `TEST_EMAIL_ADDRESS`; the original recipients are prepended to the body as `[TEST MODE — would have been sent to: …]` and the subject is prefixed `[TEST]`. The reroute lives inside `send_email()` itself so no code path can bypass it. Default `true` in every non-production environment. `EmailDispatchResult` is recorded in `audit_log` for every send.
- Email HTML bodies (below-target table, restock-alert summary, PO/dispatch cover notes) are Jinja2 templates in the same folder, sharing base styles with the PDF templates (DRY).

---

## 7. How the layers link — core workflow traceability

| # | User action (SPA) | REST endpoint(s) | Engine / service | DB tables touched | Cron dependency | Outbound side effects |
|---|---|---|---|---|---|---|
| 1 | **Run forecast** — Forecast Workbench, "Run forecast" | `POST /forecast/run` → poll `GET /forecast/runs/{id}/results`; then `POST /forecast/runs/{id}/push-to-menu` | `sync_service` (targeted sales sync of the lookback window first, so results never use stale data) → `forecast_engine.compute_category_forecasts` | reads `sales_events`, `forecast_settings`, `category_adjustments`; writes `forecast_runs`, `forecast_results`, `sync_runs`; push creates/updates `menu_plans` | `nightly_incremental_sync` keeps the window nearly current, so the pre-run targeted sync is small | none |
| 2 | **Allocate menu** — Menu Planner, "Re-allocate all / category" | `POST /menus/{id}/allocate` (manual cell edits: `PATCH /menus/{id}/allocations`) | `allocation_engine.allocate_menu_plan` (+ `compute_replenishment_differences` for the read-only cat-6/7 columns) | reads `forecast_results`, `product_scores` (score snapshots into `menu_products`), `fridge_product_targets`, `stock_snapshots`; writes `menu_allocations` | `nightly_score_recompute` supplies fresh `product_scores` for pickers and the split | none |
| 3 | **Confirm PO** — Order Builder step ③, "Confirm & send PO" | `POST /orders/build-from-menu` → edit → `POST /orders/{id}/confirm` | ordering model layer assigns `order_ref` (per-year sequence, formula 6) → `document_service.render_purchase_order_pdf` → `email_service.send_email` | writes `purchase_orders` (status draft→sent, ref, stored PDF), `purchase_order_lines`, `audit_log` | none | **PO PDF emailed to supplier** (TEST_MODE-guarded); pending qty appears in `v_stock_position` immediately |
| 4 | **Receive delivery** — order detail, "Receive delivery" | `POST /orders/{id}/receive` (accepts scanned delivery-note attachment refs) | ordering model layer; status auto-derives from line completeness (sent → partially_received → received — never set by hand); `stock_service.record_purchase_order_receipt` adds warehouse stock (§4.1); `storage_service` stores the scanned delivery note (§4.5) | writes `purchase_order_lines.qty_received`, `purchase_orders.status`, `warehouse_stock`, `stock_movements`, `attachments`, `audit_log`; `v_stock_position` shifts pending→received | none | none |
| 5 | **Confirm dispatch** — Dispatch Board, typed "DISPATCH" confirmation | `PUT /dispatches/{id}/lines` (saves; past-date saves require `confirm_past_date=true`, §4.2) → `POST /dispatches/{id}/confirm`; `GET /dispatches/{id}/notes.zip` | `stock_service.check_stock_availability` then `deduct_stock_for_dispatch_save` on every save (§4.1; NULL shelf-life products rejected); dispatch service: mark lines `is_dispatched`, snapshot purchase/sales prices + scores + shelf life onto lines → `document_service.render_dispatch_note_pdfs` (category order + withdrawal list + reminders, §6.1) → `email_service` | writes `dispatch_plans` (saved→dispatched, `dispatched_at`; UK incl. `seq` — two per day possible), `dispatch_lines` (+ snapshots), `dispatch_line_versions`, `warehouse_stock`, `stock_movements`, `audit_log`; dispatched qty also debits `v_stock_position` | `addon_service_dispatch` (05:30) may already have injected `source = addon` lines into the day's plan | **per-fridge dispatch-note PDFs emailed to logistics** (idempotent: re-confirm re-sends only on explicit "resend"; TEST_MODE-guarded) |
| 6 | **Verify restock** — Restock Verification, "Run verification" | `POST /dispatches/{id}/verify`; history via `GET /verifications` | `sync_service.sync_restock_events` for the dispatch date (targeted, pre-compute) → `verification_engine.compute_restock_verification` → `document_service.render_restock_verification_pdf` → `email_service` when discrepancies exist | reads `dispatch_lines` (qty + price snapshots), `restock_events`; writes `restock_verifications`, `verification_lines`, `sync_runs`, `audit_log`; plan status dispatched→verified | `nightly_incremental_sync`'s 3-day overlap catches RFID events that arrive after the verification ran | **restock-discrepancy alert email + PDF to ops** (only when Δ ≠ 0 or unreliable > 0; TEST_MODE-guarded) |

Cross-cutting: every mutation above writes `audit_log` (§8); every engine-backed endpoint returns a typed Pydantic result model; the Dashboard's weekly checklist is purely a read over the statuses these workflows set (`forecast_runs` exists → `menu_plans.status` → `dispatch_plans.status` → `restock_verifications` exists).

---

## 8. Auth & audit

**Authentication — JWT bearer.**

- `POST /auth/login` (email + password, bcrypt/argon2 hash in `users`) → `TokenPairResponse(BaseModel: access_token, refresh_token, expires_in)`. Access token TTL `JWT_ACCESS_TTL_MINUTES` (default 30), refresh TTL `JWT_REFRESH_TTL_DAYS` (default 14); `POST /auth/refresh` rotates the refresh token (old one revoked via a `jti` denylist table). Claims: `sub` (user id), `role`, `exp`, `jti`. `GET /auth/me` returns `CurrentUser(BaseModel: id, email, display_name, role)`.
- Dependencies in `api/deps.py`: `get_current_user` (decodes + loads user, 401 on failure) and `require_roles(*allowed_roles)` (403 when the caller's role is not in the set — the five v5 roles are **not** a strict hierarchy, so per-endpoint allow-sets replace an ordered threshold).

**Roles** (v5 briefing — replaces the earlier admin/planner/viewer draft):

| Role | May |
|---|---|
| `ops_manager` | **Full access.** Every operational workflow (forecast, scores, menus, targets, orders, dispatch, verification, weekly manual inputs), all reports, plus everything the other roles can do, including manual job triggers |
| `warehouse` | Stock operations: warehouse stock view, manual adjustments (with mandatory reason), dispatch board save/confirm, PO receipt incl. delivery-note attachments. **Read-only** on forecast and finance/reports |
| `driver` | **Read-only dispatch sheets for the assigned route** (mobile-friendly: per-fridge note view + `GET /dispatches/{id}/notes.zip` filtered to their route). Nothing else |
| `finance` | **Read-only reports** (`/reports/*`, exports). No operational mutations |
| `admin` | Users & roles, settings (fees, score weights, alert thresholds, TEST_MODE-relevant config), master data (suppliers, fridges, product overrides incl. `shelf_life_days` and `minimum_stock_qty`), `POST /sync/run`, backfill, `GET /audit` |

**Audit middleware.** A FastAPI middleware/dependency wraps every mutating request (`POST/PUT/PATCH/DELETE`, auth endpoints excluded). On success it writes one `audit_log` row:

```python
class AuditLogEntry(BaseModel):
    user_id: int
    entity_type: str          # "purchase_order", "dispatch_plan", "menu_allocation", …
    entity_id: int | None
    action: str               # "create" | "update" | "delete" | "confirm" | "receive" | "verify" | "email_sent" | …
    diff: dict[str, FieldChange] | None   # FieldChange(BaseModel: old, new); allowed dict: dynamic field names
    occurred_at: datetime
    request_path: str
```

Routers declare `entity_type`/`entity_id` via a small decorator; the diff is computed in the service layer from before/after Pydantic snapshots of the entity (only changed fields stored). Bulk grid saves (dispatch/menu lines) log one entry per plan with a compact per-line diff, not thousands of rows. Job-originated mutations (sync upserts, score batches, add-on dispatch injection) are attributed to a reserved `system` user, so `GET /audit` answers "who changed what" for both humans and cron — the accountability the workbook never had. Stock movements are additionally self-auditing via `stock_movements` (§4.1), which always carries user + timestamp.

---

## 9. Infrastructure & deferred scope (v5 briefing)

- **Hosting: Railway.com.** One FastAPI service (API + in-process APScheduler — single instance, so the advisory-lock job guard is a formality until horizontal scaling) plus Railway managed PostgreSQL. Environment variables (§1) are Railway service variables; `TEST_MODE=false` only on the production service.
- **File storage: Azure Blob Storage** via `storage_service.py` (§4.5) — attachments (scanned delivery notes) and, optionally, the stored PO/dispatch/verification PDFs (§6.1) instead of DB-resident bytes.
- **Peppol invoicing — explicitly a LATER phase.** The 3-way reconciliation (PO ↔ scanned delivery note ↔ Peppol e-invoice) is out of v1 scope. v1 deliberately lays its groundwork — POs with stored PDFs, line-level receipts, and delivery-note attachments — but no Peppol endpoint, parser, or matching logic is built now.
