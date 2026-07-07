-- ============================================================================
-- Frigoloco Forecasting Tool — PostgreSQL 16 database layer
-- Spec: 0002-port-forecasting-tool-to-web-app_2026-07-02_0815PM_UTC
-- Extended per FrigoLoco_Dev_Presentation_V5_Final.pptx (dev briefing v5):
-- warehouse stock ledger, per-fridge pricing, dual scoring, clients & add-on
-- services, dispatch changes, attachments — see Section 14.
--
-- 47 tables + 2 views + 2 functions (next_order_ref, set_updated_at trigger).
--
-- Conventions
--   * PKs        : BIGINT GENERATED ALWAYS AS IDENTITY
--   * Product/tag/vendor codes : TEXT — codes carry leading zeros
--                  (e.g. 0000053921932) and MUST NEVER be numeric.
--   * Money      : NUMERIC(10,2) (EUR)
--   * Rates/pcts : NUMERIC(6,4)  (0.0625 = 6.25 %)
--   * Timestamps : TIMESTAMPTZ; created_at/updated_at DEFAULT now(),
--                  updated_at maintained by trigger.
--   * Statuses   : TEXT + CHECK constraint (readable in psql, still strict).
-- ============================================================================

BEGIN;

-- ============================================================================
-- SECTION 1 · MASTERS — VENDOR-SYNCED (upserted by sync jobs)
-- Local override columns (active, display_name, delivery_instructions_override)
-- are never overwritten by the sync.
-- ============================================================================

CREATE TABLE product_categories (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,           -- e.g. '1. Cold Dishes'
    sort_order  INT  NOT NULL,                  -- legacy Excel order (kept)
    -- Dev briefing v5: category order on the printed dispatch sheet
    -- (Hot -> Frozen -> Salads -> Wraps -> Granolas -> Soups -> Desserts ->
    --  Drinks -> Snacks). Seeded further below.
    dispatch_display_order INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE suppliers (
    -- App-owned master, but created here because products references it.
    -- Seeded from the "Supplier Info" sheet (name, emails, warehouse address).
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    emails             TEXT[] NOT NULL DEFAULT '{}',   -- multiple recipients per supplier
    warehouse_address  TEXT,
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_code     TEXT NOT NULL UNIQUE,      -- vendor code, leading zeros — TEXT, never numeric
    name             TEXT NOT NULL,             -- vendor name
    display_name     TEXT,                      -- local override, never overwritten by sync
    category_id      BIGINT REFERENCES product_categories (id) ON DELETE RESTRICT,
    supplier_id      BIGINT REFERENCES suppliers (id) ON DELETE RESTRICT,  -- vendor "brand"
    purchase_price   NUMERIC(10,2),             -- vendor "reference" (buy price)
    sales_price      NUMERIC(10,2),             -- vendor sell price (cents → EUR at sync)
    vat_rate         NUMERIC(6,4),              -- e.g. 0.0600
    -- shelf_life_days (DLC) stays NULLABLE: 218 of 540 products have no DLC at
    -- migration. APP-LAYER RULE (dev briefing v5): dispatching a product whose
    -- shelf_life_days IS NULL is BLOCKED until the value is filled in.
    shelf_life_days  INT,                       -- vendor expiryDays
    active           BOOLEAN NOT NULL DEFAULT TRUE,  -- local override
    -- Dev briefing v5: 20 'Box n°' test catalog lines — excluded from every
    -- engine (forecast, scoring, allocation, stock position) when TRUE.
    is_test          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE facilities (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor_facility_id     TEXT NOT NULL UNIQUE,   -- natural key from GET /facility
    name                   TEXT NOT NULL,
    delivery_address       TEXT,
    delivery_instructions  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE fridges (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor_code   TEXT NOT NULL UNIQUE,          -- e.g. 'if-0000271'
    name          TEXT NOT NULL,                 -- client name, e.g. 'ABB Zaventem'
    display_name  TEXT,                          -- local override, never overwritten by sync
    facility_id   BIGINT REFERENCES facilities (id) ON DELETE SET NULL,
    delivery_instructions_override TEXT,         -- local override of facility instructions
    active        BOOLEAN NOT NULL DEFAULT TRUE, -- local override
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- SECTION 2 · MASTERS — APP-OWNED (Admin screen)
-- (suppliers is defined in Section 1 for FK-ordering reasons)
-- ============================================================================

CREATE TABLE roles (
    id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE                   -- admin | planner | viewer
);

CREATE TABLE users (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    full_name      TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    role_id        BIGINT NOT NULL REFERENCES roles (id) ON DELETE RESTRICT,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- SECTION 3 · TELEMETRY — VENDOR-SYNCED, APPEND-ONLY EVENT STORES
-- Idempotent upsert on natural keys; rows are never mutated by the app.
-- ============================================================================

CREATE TABLE sales_events (
    -- One row = one unit sold (GET /purchases: 1 product row = 1 unit).
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tag_id             TEXT NOT NULL UNIQUE,     -- RFID tag = natural key (a tag sells once)
    fridge_id          BIGINT NOT NULL REFERENCES fridges (id) ON DELETE RESTRICT,
    product_id         BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    sold_at            TIMESTAMPTZ NOT NULL,
    unit_price         NUMERIC(10,2) NOT NULL,   -- vendor cents → EUR at sync
    vat_rate           NUMERIC(6,4),
    refund_status      TEXT,                     -- vendor value, NULL = not refunded
    discount_provider  TEXT,                     -- splits Frigoloco-vs-customer discounts
    discount_amount    NUMERIC(10,2) NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE restock_events (
    -- One row = one RFID tag added/removed (GET /restock).
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    epc         TEXT NOT NULL,                   -- RFID tag EPC
    fridge_id   BIGINT NOT NULL REFERENCES fridges (id) ON DELETE RESTRICT,
    product_id  BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    event_at    TIMESTAMPTZ NOT NULL,
    action      TEXT NOT NULL,                   -- vendor action, e.g. 'ADDED'
    tag_status  TEXT,                            -- 'UNRELIABLE' handled separately in verification
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (epc, event_at)                       -- a tag can be re-used across restocks
);

CREATE TABLE product_reviews (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor_review_id  TEXT UNIQUE,               -- natural key when the vendor provides one
    product_id        BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    fridge_id         BIGINT REFERENCES fridges (id) ON DELETE SET NULL,
    rating            SMALLINT NOT NULL,         -- vendor scale; rating = 1 counts positive
    reviewed_at       TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE stock_snapshots (
    -- Optional cache of GET /stock/current. Live stock is never truth here —
    -- the sync job appends a snapshot; v_below_target reads the latest one.
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fridge_id    BIGINT NOT NULL REFERENCES fridges (id) ON DELETE CASCADE,
    product_id   BIGINT NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    quantity     INT NOT NULL,
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- SECTION 4 · SYNC BOOKKEEPING
-- ============================================================================

CREATE TABLE sync_runs (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    endpoint     TEXT NOT NULL,                  -- purchases | restock | producttype | ...
    window_from  TIMESTAMPTZ,
    window_to    TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'succeeded', 'failed')),
    rows_fetched   INT,
    rows_upserted  INT,
    error        TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

-- ============================================================================
-- SECTION 5 · FORECASTING
-- ============================================================================

CREATE TABLE forecast_settings (
    -- Per fridge/client: 'Minimum Qty' and '# Days To Be Filled' (Forecast V2).
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fridge_id     BIGINT NOT NULL UNIQUE REFERENCES fridges (id) ON DELETE CASCADE,
    min_qty       INT NOT NULL DEFAULT 0,        -- holiday threshold: day excluded when sold <= min_qty
    days_to_fill  INT NOT NULL DEFAULT 0,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE category_adjustments (
    -- The '% Adjust' row of Forecast V2, persisted per category.
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id  BIGINT NOT NULL UNIQUE REFERENCES product_categories (id) ON DELETE CASCADE,
    pct_adjust   NUMERIC(6,4) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE forecast_runs (
    -- Every run is kept (Excel overwrote the previous one).
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dispatch_day_name  TEXT NOT NULL CHECK (dispatch_day_name IN
        ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')),
    weeks_back         INT NOT NULL DEFAULT 3,
    run_by             BIGINT REFERENCES users (id) ON DELETE SET NULL,
    run_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE forecast_results (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    forecast_run_id BIGINT NOT NULL REFERENCES forecast_runs (id) ON DELETE CASCADE,
    fridge_id      BIGINT NOT NULL REFERENCES fridges (id) ON DELETE CASCADE,
    category_id    BIGINT NOT NULL REFERENCES product_categories (id) ON DELETE CASCADE,
    forecast_qty   NUMERIC(10,2) NOT NULL,       -- fractional (Excel kept e.g. 2.3333)
    sold_qty       INT NOT NULL DEFAULT 0,       -- diagnostics: lookback sold
    added_qty      INT NOT NULL DEFAULT 0,       -- diagnostics: lookback added
    valid_days     INT NOT NULL DEFAULT 0,
    excluded_days  INT NOT NULL DEFAULT 0,       -- "holiday" days (sold <= min_qty)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (forecast_run_id, fridge_id, category_id)
);

-- ============================================================================
-- SECTION 6 · SCORING
-- ============================================================================

CREATE TABLE score_weights (
    -- DUAL SCORING (dev briefing v5) — one weight row per scope:
    --   'global' : 0.55 sold_pct + 0.30 margin + 0.15 review  (all fridges)
    --   'fridge' : 0.70 fridge sold_pct + 0.30 fridge review  (margin unused)
    -- The effective product score per fridge combines the two 50/50:
    --   combined = 0.5 * global_score + 0.5 * fridge_score   (app layer)
    -- APP-LAYER RULE: new products with <= 250 lifetime sales use the AVERAGE
    -- global score as a placeholder until they have enough history.
    -- (Supersedes the single Excel weight set 0.62/0.33/0.05.)
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scope              TEXT NOT NULL UNIQUE CHECK (scope IN ('global', 'fridge')),
    sold_pct_weight    NUMERIC(6,4) NOT NULL,
    margin_pct_weight  NUMERIC(6,4) NOT NULL,
    review_pct_weight  NUMERIC(6,4) NOT NULL,
    updated_by         BIGINT REFERENCES users (id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (sold_pct_weight + margin_pct_weight + review_pct_weight = 1.0000)
);

CREATE TABLE product_scores (
    -- final_score = w_sold * sold_pct + w_margin * margin_pct + w_review * review_pct
    --   sold_pct   = sold / added                     (365-day window)
    --   margin_pct = (sell_ex_vat - buy) / sell_ex_vat
    --   review_pct = (pos - neg) / (pos + neg)        (can be negative)
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id        BIGINT NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    window_start      DATE NOT NULL,
    window_end        DATE NOT NULL,
    sold_qty          INT NOT NULL DEFAULT 0,
    added_qty         INT NOT NULL DEFAULT 0,
    positive_reviews  INT NOT NULL DEFAULT 0,
    negative_reviews  INT NOT NULL DEFAULT 0,
    sold_pct          NUMERIC(6,4),
    margin_pct        NUMERIC(6,4),
    review_pct        NUMERIC(6,4),               -- range [-1, 1]
    final_score       NUMERIC(6,4),
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- SECTION 7 · MENU
-- ============================================================================

CREATE TABLE menu_plans (
    -- Weeks planned in advance (dev briefing v5): fully supported by keying on
    -- week_start_date — any number of future weeks can exist as 'draft' or
    -- 'allocated' plans; no extra status value is required.
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    week_start_date  DATE NOT NULL,
    day_name         TEXT NOT NULL CHECK (day_name IN
        ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')),
    status           TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'allocated', 'pushed')),
    forecast_run_id  BIGINT REFERENCES forecast_runs (id) ON DELETE SET NULL,  -- provenance
    created_by       BIGINT REFERENCES users (id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (week_start_date, day_name)
);

CREATE TABLE menu_products (
    -- The products composed onto the menu per category (replaces DVListsForMenu slots).
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    menu_plan_id    BIGINT NOT NULL REFERENCES menu_plans (id) ON DELETE CASCADE,
    category_id     BIGINT NOT NULL REFERENCES product_categories (id) ON DELETE RESTRICT,
    product_id      BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    score_snapshot  NUMERIC(6,4),                -- Final Score at composition time
    position        INT NOT NULL DEFAULT 0,      -- display order within the category
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (menu_plan_id, product_id)
);

CREATE TABLE menu_allocations (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    menu_plan_id  BIGINT NOT NULL REFERENCES menu_plans (id) ON DELETE CASCADE,
    fridge_id     BIGINT NOT NULL REFERENCES fridges (id) ON DELETE CASCADE,
    product_id    BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    quantity      INT NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'engine'
                  CHECK (source IN ('engine', 'manual')),  -- manual cells survive re-allocation
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (menu_plan_id, fridge_id, product_id)
);

-- ============================================================================
-- SECTION 8 · ORDERING
-- ============================================================================

CREATE TABLE order_ref_counters (
    -- Per-year sequence backing next_order_ref(). Row-locked, race-safe —
    -- replaces the Excel "scan Order History for max ref" pattern.
    year      INT PRIMARY KEY,
    last_seq  INT NOT NULL DEFAULT 0
);

CREATE TABLE purchase_orders (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_ref                TEXT UNIQUE,        -- 'YYYY-NNNNN'; NULL while draft, assigned at confirm
    supplier_id              BIGINT NOT NULL REFERENCES suppliers (id) ON DELETE RESTRICT,
    status                   TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft', 'sent', 'partially_received',
                                               'received', 'cancelled')),
    order_date               DATE,
    expected_delivery_date   DATE,
    delivery_address         TEXT,
    comment                  TEXT,
    total_ex_vat             NUMERIC(10,2),      -- cached line totals
    total_inc_vat            NUMERIC(10,2),
    created_by               BIGINT REFERENCES users (id) ON DELETE SET NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status = 'draft' OR order_ref IS NOT NULL)  -- every non-draft order has a ref
);

CREATE TABLE purchase_order_lines (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_order_id  BIGINT NOT NULL REFERENCES purchase_orders (id) ON DELETE CASCADE,
    product_id         BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    qty_ordered        INT NOT NULL CHECK (qty_ordered >= 0),
    qty_received       INT NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
    unit_price         NUMERIC(10,2) NOT NULL,   -- purchase price snapshot at order time
    vat_rate           NUMERIC(6,4) NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (purchase_order_id, product_id)
);

-- ============================================================================
-- SECTION 9 · DISPATCH
-- ============================================================================

CREATE TABLE dispatch_plans (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    week_start_date  DATE NOT NULL,
    iso_week         INT NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
    day_name         TEXT NOT NULL CHECK (day_name IN
        ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')),
    -- Dev briefing v5: up to 2 dispatches per day — seq disambiguates them.
    seq              SMALLINT NOT NULL DEFAULT 1 CHECK (seq >= 1),
    status           TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'saved', 'dispatched', 'verified')),
    dispatched_at    TIMESTAMPTZ,
    -- Dev briefing v5: saving a plan dated in the past requires an explicit
    -- user confirmation, recorded here.
    confirmed_past_date BOOLEAN NOT NULL DEFAULT FALSE,
    created_by       BIGINT REFERENCES users (id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (week_start_date, day_name, seq)
);

CREATE TABLE dispatch_lines (
    -- Snapshot columns mirror Global Dispatch History: price/margin/score/shelf
    -- life are frozen at confirm time so history is immune to catalog changes.
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dispatch_plan_id         BIGINT NOT NULL REFERENCES dispatch_plans (id) ON DELETE CASCADE,
    fridge_id                BIGINT NOT NULL REFERENCES fridges (id) ON DELETE RESTRICT,
    product_id               BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    quantity                 INT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    is_dispatched            BOOLEAN NOT NULL DEFAULT FALSE,
    purchase_price_snapshot  NUMERIC(10,2),
    sales_price_snapshot     NUMERIC(10,2),
    vat_rate_snapshot        NUMERIC(6,4),
    score_snapshot           NUMERIC(6,4),
    shelf_life_days_snapshot INT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dispatch_plan_id, fridge_id, product_id)
);

-- ============================================================================
-- SECTION 10 · VERIFICATION
-- ============================================================================

CREATE TABLE restock_verifications (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dispatch_plan_id      BIGINT NOT NULL REFERENCES dispatch_plans (id) ON DELETE CASCADE,
    run_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_by                BIGINT REFERENCES users (id) ON DELETE SET NULL,
    total_diff_qty        INT NOT NULL DEFAULT 0,
    total_diff_value      NUMERIC(10,2) NOT NULL DEFAULT 0,
    total_unreliable_qty  INT NOT NULL DEFAULT 0,
    alert_sent            BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE verification_lines (
    -- Per product x fridge: diff = added_qty - dispatched_qty,
    -- diff_value = diff * purchase price. UNRELIABLE tags are counted
    -- separately and excluded from the reliable added_qty total.
    id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    restock_verification_id   BIGINT NOT NULL REFERENCES restock_verifications (id) ON DELETE CASCADE,
    fridge_id                 BIGINT NOT NULL REFERENCES fridges (id) ON DELETE RESTRICT,
    product_id                BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    dispatched_qty            INT NOT NULL DEFAULT 0,
    added_qty                 INT NOT NULL DEFAULT 0,   -- reliable tags only
    unreliable_qty            INT NOT NULL DEFAULT 0,
    diff_qty                  INT NOT NULL DEFAULT 0,
    diff_value                NUMERIC(10,2) NOT NULL DEFAULT 0
);

-- ============================================================================
-- SECTION 11 · TARGETS (Snacks & Drinks Target Map)
-- ============================================================================

CREATE TABLE fridge_product_targets (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fridge_id   BIGINT NOT NULL REFERENCES fridges (id) ON DELETE CASCADE,
    product_id  BIGINT NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    target_qty  INT NOT NULL DEFAULT 0 CHECK (target_qty >= 0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fridge_id, product_id)
);

-- ============================================================================
-- SECTION 12 · REPORTING
-- ============================================================================

CREATE TABLE weekly_summaries (
    -- ISO-8601 weeks throughout (fixes the dual week-numbering defect).
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    iso_year            INT NOT NULL,
    iso_week            INT NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
    -- Manual inputs (the Weekly & Monthly Return form fields):
    catering_turnover   NUMERIC(10,2),
    tgtg_turnover       NUMERIC(10,2),
    catering_food_cost  NUMERIC(10,2),
    logistics_cost      NUMERIC(10,2),
    drops               INT,
    unsold_items        INT,
    remarks             TEXT,
    -- API-derived aggregates cached at compute time (sales, refunds, discounts,
    -- net revenue, added food cost, dispatch food cost, ...):
    api_aggregates      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (iso_year, iso_week)
);

CREATE TABLE fee_settings (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pos_software_pct    NUMERIC(6,4) NOT NULL,   -- POS/software fee, fraction of turnover
    rfid_fee            NUMERIC(10,2) NOT NULL,  -- per-unit RFID tag fee (EUR)
    discount_providers  TEXT[] NOT NULL DEFAULT '{}',  -- providers counted as Frigoloco discount
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE fridge_fees (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fridge_id     BIGINT NOT NULL UNIQUE REFERENCES fridges (id) ON DELETE CASCADE,
    yearly_fee    NUMERIC(10,2) NOT NULL DEFAULT 0,
    fraction_pct  NUMERIC(6,4) NOT NULL DEFAULT 0,
    contract_end  DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE service_additionals (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fridge_id   BIGINT NOT NULL REFERENCES fridges (id) ON DELETE CASCADE,
    month       DATE NOT NULL CHECK (EXTRACT(DAY FROM month) = 1),  -- first day of month
    amount      NUMERIC(10,2) NOT NULL,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- SECTION 13 · AUDIT
-- ============================================================================

CREATE TABLE audit_log (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT REFERENCES users (id) ON DELETE SET NULL,
    entity     TEXT NOT NULL,                    -- table / aggregate name
    entity_id  BIGINT,
    action     TEXT NOT NULL,                    -- create | update | delete | confirm | ...
    diff       JSONB,                            -- before/after field-level diff
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- SECTION 14 · PRESENTATION-DRIVEN EXTENSIONS (dev briefing v5)
-- Mandated by FrigoLoco_Dev_Presentation_V5_Final.pptx.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 14.1 Warehouse stock (non-negotiable per deck)
-- One row per product; qty >= 0 is a DB CHECK — "negative stock impossible"
-- is enforced here, never left to UI validation. Every PO receipt adds,
-- every dispatch save deducts, a cancellation reverses; each change also
-- writes a stock_movements row.
-- ----------------------------------------------------------------------------

CREATE TABLE warehouse_stock (
    product_id  BIGINT PRIMARY KEY REFERENCES products (id) ON DELETE CASCADE,
    qty         INT NOT NULL DEFAULT 0 CHECK (qty >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE stock_movements (
    -- Append-only ledger of every warehouse_stock change.
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id     BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    movement_type  TEXT NOT NULL CHECK (movement_type IN
        ('po_receipt', 'dispatch_deduct', 'manual_adjustment', 'cancellation_reversal')),
    qty_delta      INT NOT NULL,                 -- signed: receipts +, deductions -
    reason         TEXT,                         -- mandatory for manual adjustments (CHECK below)
    reference_entity  TEXT,                      -- e.g. 'purchase_order', 'dispatch_plan'
    reference_id      BIGINT,
    user_id        BIGINT REFERENCES users (id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (movement_type <> 'manual_adjustment' OR reason IS NOT NULL)
);

-- ----------------------------------------------------------------------------
-- 14.2 Per-fridge pricing
-- The vendor exposes per-fridge sell prices; this maps them onto internal
-- fridge ids. Falls back to products.sales_price when no row exists.
-- ----------------------------------------------------------------------------

CREATE TABLE fridge_product_prices (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fridge_id   BIGINT NOT NULL REFERENCES fridges (id) ON DELETE CASCADE,
    product_id  BIGINT NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    price       NUMERIC(10,2) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fridge_id, product_id)
);

-- ----------------------------------------------------------------------------
-- 14.3 Dual scoring — per-fridge score store
-- (score_weights in Section 6 now carries scope = 'global' | 'fridge'.)
-- fridge_score = w_sold * fridge_sold_pct + w_review * fridge_review_pct
-- combined (app layer) = 0.5 * global + 0.5 * fridge.
-- ----------------------------------------------------------------------------

CREATE TABLE product_fridge_scores (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id    BIGINT NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    fridge_id     BIGINT NOT NULL REFERENCES fridges (id) ON DELETE CASCADE,
    window_start  DATE NOT NULL,
    window_end    DATE NOT NULL,
    sold_pct      NUMERIC(6,4),                  -- this fridge's sold/added
    review_pct    NUMERIC(6,4),                  -- this fridge's review score, [-1, 1]
    fridge_score  NUMERIC(6,4),
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, fridge_id, window_end)
);

-- ----------------------------------------------------------------------------
-- 14.4 Clients (the businesses hosting fridges) + service catalog
-- ----------------------------------------------------------------------------

CREATE TABLE clients (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    location       TEXT,
    workers_count  INT,
    worker_type    TEXT CHECK (worker_type IN ('white_collar', 'blue_collar', 'mixed')),
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fridges belong to clients. ALTER (not inline) because clients is created
-- after fridges; a fridge can be temporarily unassigned.
ALTER TABLE fridges
    ADD COLUMN client_id BIGINT REFERENCES clients (id) ON DELETE SET NULL;

CREATE TABLE client_interventions (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id          BIGINT NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
    fridge_id          BIGINT REFERENCES fridges (id) ON DELETE SET NULL,
    intervention_type  TEXT NOT NULL CHECK (intervention_type IN
        ('technical', 'cleaning', 'hardware_replacement', 'other')),
    description        TEXT,
    occurred_at        TIMESTAMPTZ NOT NULL,
    user_id            BIGINT REFERENCES users (id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE client_preferences (
    -- Free-text preference notes (e.g. "no pork", "prefers vegan options").
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id   BIGINT NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
    preference  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE service_types (
    -- Catalog of billable services (seeded below): fridge_rental,
    -- coffee_machine, fruit_delivery, business_lunch, catering.
    id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE client_service_fees (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id        BIGINT NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
    service_type_id  BIGINT NOT NULL REFERENCES service_types (id) ON DELETE RESTRICT,
    monthly_fee      NUMERIC(10,2) NOT NULL DEFAULT 0,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (client_id, service_type_id)
);

-- ----------------------------------------------------------------------------
-- 14.5 Add-on services
-- ----------------------------------------------------------------------------

CREATE TABLE addon_service_schedules (
    -- Recurring deliveries, e.g. 5 kg fruit every Monday + Wednesday.
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id         BIGINT NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
    service_type_id   BIGINT NOT NULL REFERENCES service_types (id) ON DELETE RESTRICT,
    quantity          NUMERIC(10,2) NOT NULL,
    unit              TEXT NOT NULL,             -- 'kg', 'pieces', ...
    recurrence_days   TEXT[] NOT NULL DEFAULT '{}',  -- day names, e.g. {Monday,Wednesday}
    exclude_holidays  BOOLEAN NOT NULL DEFAULT TRUE,
    active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE business_lunch_orders (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id     BIGINT NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
    order_date    DATE NOT NULL,
    po_reference  TEXT,                          -- client's own PO reference
    description   TEXT,
    amount        NUMERIC(10,2) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- 14.6 Dispatch withdrawal lines (driver pull list)
-- Products whose remaining shelf life (DLC) falls below the coverage window
-- are pulled from the fridge on delivery. resolution is NULL until the driver
-- reports the outcome.
-- ----------------------------------------------------------------------------

CREATE TABLE dispatch_withdrawal_lines (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dispatch_plan_id  BIGINT NOT NULL REFERENCES dispatch_plans (id) ON DELETE CASCADE,
    fridge_id         BIGINT NOT NULL REFERENCES fridges (id) ON DELETE RESTRICT,
    product_id        BIGINT NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    qty               INT NOT NULL CHECK (qty >= 0),
    reason            TEXT NOT NULL CHECK (reason IN ('short_dlc', 'other')),
    resolution        TEXT CHECK (resolution IN ('loss', 'return_to_warehouse')),  -- NULL until resolved
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- 14.7 Azure Blob attachments
-- e.g. photographed supplier delivery notes attached to PO receipts.
-- ----------------------------------------------------------------------------

CREATE TABLE attachments (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type   TEXT NOT NULL,                 -- 'purchase_order', 'dispatch_plan', ...
    entity_id     BIGINT NOT NULL,
    blob_path     TEXT NOT NULL,                 -- path inside the Azure Blob container
    filename      TEXT NOT NULL,
    content_type  TEXT,
    uploaded_by   BIGINT REFERENCES users (id) ON DELETE SET NULL,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Section 14 indexes
CREATE INDEX idx_stock_movements_product_created ON stock_movements (product_id, created_at);
CREATE INDEX idx_product_fridge_scores_lookup    ON product_fridge_scores (product_id, fridge_id, computed_at DESC);
CREATE INDEX idx_attachments_entity              ON attachments (entity_type, entity_id);
CREATE INDEX idx_dispatch_withdrawal_lines_plan  ON dispatch_withdrawal_lines (dispatch_plan_id);
CREATE INDEX idx_client_interventions_client     ON client_interventions (client_id, occurred_at);

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Race-safe order-reference generator: 'YYYY-NNNNN' (zero-padded to 5).
-- The row lock (SELECT ... FOR UPDATE) serializes concurrent confirms within
-- a year; the counter row is created on first use each year.
CREATE OR REPLACE FUNCTION next_order_ref()
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    current_year INT := EXTRACT(YEAR FROM now())::INT;
    new_seq INT;
BEGIN
    INSERT INTO order_ref_counters (year, last_seq)
    VALUES (current_year, 0)
    ON CONFLICT (year) DO NOTHING;

    SELECT last_seq INTO new_seq
    FROM order_ref_counters
    WHERE year = current_year
    FOR UPDATE;

    new_seq := new_seq + 1;

    UPDATE order_ref_counters
    SET last_seq = new_seq
    WHERE year = current_year;

    RETURN current_year::TEXT || '-' || lpad(new_seq::TEXT, 5, '0');
END;
$$;

-- Generic updated_at maintenance.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- Attach the updated_at trigger to every table that has the column.
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'product_categories', 'suppliers', 'products', 'facilities', 'fridges',
        'users', 'forecast_settings', 'category_adjustments', 'score_weights',
        'menu_plans', 'menu_allocations', 'purchase_orders', 'purchase_order_lines',
        'dispatch_plans', 'dispatch_lines', 'fridge_product_targets',
        'weekly_summaries', 'fee_settings', 'fridge_fees', 'service_additionals',
        -- Section 14 (dev briefing v5)
        'warehouse_stock', 'fridge_product_prices', 'clients',
        'client_service_fees', 'addon_service_schedules', 'dispatch_withdrawal_lines'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%I_updated_at
             BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
            tbl, tbl
        );
    END LOOP;
END;
$$;

-- ============================================================================
-- VIEWS
-- ============================================================================

-- ----------------------------------------------------------------------------
-- v_stock_position — mirrors the "Refresh Stock And Ordered" Office Script
-- (Stock & Ordered sheet), always live, never stored:
--
--   pending_to_receive = SUM(qty_ordered)  of orders with status 'sent'
--                        (Excel status "Pending")
--   received           = SUM(qty_received) of orders with status 'received'
--                        or 'partially_received' (Excel status "Received";
--                        Cancelled excluded)
--   dispatched         = SUM(dispatch_lines.quantity) where is_dispatched
--   stock_and_ordered  = pending_to_receive + received
--   current_position   = pending_to_receive + received - dispatched
--                        ("Currently In Stock & Ordered")
--
-- LEGACY SEMANTIC vs INTENTIONAL IMPROVEMENT: Excel classified a WHOLE order
-- as either Pending or Received by its single status cell — a partially
-- delivered order counted 100% one way or the other. This view improves that
-- to per-line quantities: a 'partially_received' order contributes its
-- qty_received to `received` line by line. The not-yet-received remainder of
-- a partially received order is intentionally NOT counted as pending, exactly
-- matching the Excel formula where "Pending" summed only Pending-status
-- orders. This is a deliberate, documented deviation — flag any parity-test
-- differences on partially received orders against this comment.
-- ----------------------------------------------------------------------------
CREATE VIEW v_stock_position AS
WITH order_totals AS (
    SELECT
        pol.product_id,
        COALESCE(SUM(pol.qty_ordered)  FILTER (WHERE po.status = 'sent'), 0) AS pending_to_receive,
        COALESCE(SUM(pol.qty_received) FILTER (WHERE po.status IN ('received', 'partially_received')), 0) AS received
    FROM purchase_order_lines pol
    JOIN purchase_orders po ON po.id = pol.purchase_order_id
    WHERE po.status IN ('sent', 'partially_received', 'received')   -- draft + cancelled excluded
    GROUP BY pol.product_id
),
dispatch_totals AS (
    SELECT
        dl.product_id,
        SUM(dl.quantity) AS dispatched
    FROM dispatch_lines dl
    WHERE dl.is_dispatched
    GROUP BY dl.product_id
)
SELECT
    p.id                                   AS product_id,
    p.product_code,
    COALESCE(p.display_name, p.name)       AS product_name,
    pc.name                                AS category_name,
    s.name                                 AS supplier_name,
    COALESCE(ot.pending_to_receive, 0)     AS pending_to_receive,
    COALESCE(ot.received, 0)               AS received,
    COALESCE(dt.dispatched, 0)             AS dispatched,
    COALESCE(ot.pending_to_receive, 0) + COALESCE(ot.received, 0)
                                           AS stock_and_ordered,
    COALESCE(ot.pending_to_receive, 0) + COALESCE(ot.received, 0)
        - COALESCE(dt.dispatched, 0)       AS current_position
FROM products p
LEFT JOIN product_categories pc ON pc.id = p.category_id
LEFT JOIN suppliers s           ON s.id  = p.supplier_id
LEFT JOIN order_totals ot       ON ot.product_id = p.id
LEFT JOIN dispatch_totals dt    ON dt.product_id = p.id;

-- ----------------------------------------------------------------------------
-- v_below_target — fridge/product targets vs the LATEST stock snapshot.
-- Feeds the below-target alert job and the Dashboard KPI.
-- ----------------------------------------------------------------------------
CREATE VIEW v_below_target AS
WITH latest_stock AS (
    SELECT DISTINCT ON (ss.fridge_id, ss.product_id)
        ss.fridge_id,
        ss.product_id,
        ss.quantity,
        ss.captured_at
    FROM stock_snapshots ss
    ORDER BY ss.fridge_id, ss.product_id, ss.captured_at DESC
)
SELECT
    t.fridge_id,
    COALESCE(f.display_name, f.name)  AS fridge_name,
    t.product_id,
    p.product_code,
    COALESCE(p.display_name, p.name)  AS product_name,
    t.target_qty,
    COALESCE(ls.quantity, 0)          AS current_qty,
    t.target_qty - COALESCE(ls.quantity, 0) AS shortfall,
    ls.captured_at                    AS stock_as_of
FROM fridge_product_targets t
JOIN fridges f  ON f.id = t.fridge_id
JOIN products p ON p.id = t.product_id
LEFT JOIN latest_stock ls
       ON ls.fridge_id = t.fridge_id AND ls.product_id = t.product_id
WHERE t.target_qty > COALESCE(ls.quantity, 0);

-- ============================================================================
-- INDEXES (hot paths)
-- ============================================================================

-- Telemetry aggregation windows (forecast lookback, scoring, weekly reports)
CREATE INDEX idx_sales_events_fridge_sold_at    ON sales_events (fridge_id, sold_at);
CREATE INDEX idx_sales_events_product_sold_at   ON sales_events (product_id, sold_at);
CREATE INDEX idx_restock_events_fridge_event_at ON restock_events (fridge_id, event_at);
CREATE INDEX idx_restock_events_product_event_at ON restock_events (product_id, event_at);

-- Dispatch grid load + stock-position dispatched aggregate
CREATE INDEX idx_dispatch_lines_plan            ON dispatch_lines (dispatch_plan_id);
CREATE INDEX idx_dispatch_lines_product_dispatched ON dispatch_lines (product_id, is_dispatched);

-- Stock-position order aggregates
CREATE INDEX idx_purchase_order_lines_product   ON purchase_order_lines (product_id);

-- Latest-score lookup (Menu Planner pickers, allocation engine)
CREATE INDEX idx_product_scores_product_computed ON product_scores (product_id, computed_at DESC);

-- Audit drill-down per entity
CREATE INDEX idx_audit_log_entity               ON audit_log (entity, entity_id);

-- Latest-snapshot lookup for v_below_target
CREATE INDEX idx_stock_snapshots_latest         ON stock_snapshots (fridge_id, product_id, captured_at DESC);

-- Sync dashboard (last run per endpoint)
CREATE INDEX idx_sync_runs_endpoint_started     ON sync_runs (endpoint, started_at DESC);

-- Menu grid load
CREATE INDEX idx_menu_allocations_plan          ON menu_allocations (menu_plan_id);

-- ============================================================================
-- SEED DATA
-- ============================================================================

INSERT INTO product_categories (name, sort_order) VALUES
    ('1. Cold Dishes',          1),
    ('2. Wraps & Sandwiches',   2),
    ('3. Warm Dishes Jar',      3),
    ('4. Warm Dishes',          4),
    ('5. Desserts',             5),
    ('6. Snacks',               6),
    ('7. Drinks',               7),
    ('8. Breakfast',            8),
    ('9. Soup',                 9),
    ('10. Frozen Warm Dishes', 10);

-- Dual-scoring weights (dev briefing v5; supersedes Excel's 0.62/0.33/0.05)
INSERT INTO score_weights (scope, sold_pct_weight, margin_pct_weight, review_pct_weight) VALUES
    ('global', 0.5500, 0.3000, 0.1500),
    ('fridge', 0.7000, 0.0000, 0.3000);

-- Default fees (Weekly & Monthly Return configuration)
INSERT INTO fee_settings (pos_software_pct, rfid_fee, discount_providers)
VALUES (0.0900, 0.10, '{}');

INSERT INTO roles (name) VALUES
    ('admin'),
    ('planner'),
    ('viewer');

-- Service catalog (dev briefing v5)
INSERT INTO service_types (name) VALUES
    ('fridge_rental'),
    ('coffee_machine'),
    ('fruit_delivery'),
    ('business_lunch'),
    ('catering');

-- Dispatch-sheet category order (dev briefing v5):
--   Hot -> Frozen -> Salads -> Wraps -> Granolas -> Soups -> Desserts ->
--   Drinks -> Snacks
-- BEST-EFFORT mapping of the deck's 9 buckets onto the 10 legacy categories
-- ("Hot" covers both Warm Dishes and Warm Dishes Jar; Granolas = Breakfast;
-- Salads = Cold Dishes). CONFIRM WITH THE BUSINESS before go-live.
UPDATE product_categories SET dispatch_display_order = 1  WHERE name = '4. Warm Dishes';
UPDATE product_categories SET dispatch_display_order = 2  WHERE name = '3. Warm Dishes Jar';
UPDATE product_categories SET dispatch_display_order = 3  WHERE name = '10. Frozen Warm Dishes';
UPDATE product_categories SET dispatch_display_order = 4  WHERE name = '1. Cold Dishes';
UPDATE product_categories SET dispatch_display_order = 5  WHERE name = '2. Wraps & Sandwiches';
UPDATE product_categories SET dispatch_display_order = 6  WHERE name = '8. Breakfast';
UPDATE product_categories SET dispatch_display_order = 7  WHERE name = '9. Soup';
UPDATE product_categories SET dispatch_display_order = 8  WHERE name = '5. Desserts';
UPDATE product_categories SET dispatch_display_order = 9  WHERE name = '7. Drinks';
UPDATE product_categories SET dispatch_display_order = 10 WHERE name = '6. Snacks';

COMMIT;
