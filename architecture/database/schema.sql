-- ============================================================================
-- FrigoLoco Cloud ERP — PostgreSQL 16 Database Schema
-- ============================================================================
-- Source spec : specs/0001-frigoloco-excel-to-cloud-erp_2026-07-02_0810PM_UTC
-- Replaces    : Smart Fridge Forecasting Tool V5.xlsx,
--               Weekly & Monthly Return V2.xlsx, 3 template workbooks,
--               26 Office Scripts, 4 Power Automate flows.
--
-- Conventions
--   * Monetary columns .............. BIGINT minor units (cents), matching the
--                                     Husky API int64 contract. CHANGED 2026-07-03
--                                     (user decision, migration 0002): was
--                                     NUMERIC(10,2) euros. Columns keep their
--                                     names (purchase_price, sales_price, ...);
--                                     euros exist only at the API presentation
--                                     edge (the JSON stays a 2-decimal euro
--                                     string, so the frontend is untouched).
--   * VAT rates / score fractions ... NUMERIC(6,4) fractions (0.06 = 6 %) — NOT
--                                     money, unchanged. So are forecast_qty and
--                                     pos_fee_pct_snapshot.
--   * Product codes ................. TEXT, never integers — barcodes keep
--                                     their leading zeros.
--   * Audit columns ................. created_at/updated_at TIMESTAMPTZ.
--   * Weekdays ...................... ISO smallint, 1 = Monday … 7 = Sunday.
--
-- Idempotency: enums are wrapped in duplicate-safe DO blocks, tables and
-- indexes use IF NOT EXISTS, functions use CREATE OR REPLACE, seed inserts
-- use ON CONFLICT DO NOTHING. To rebuild from scratch instead, run:
--     DROP SCHEMA public CASCADE; CREATE SCHEMA public;
-- and then re-apply this file.
-- ============================================================================

BEGIN;

-- ============================================================================
-- SECTION 1 — STATUS / TYPE DOMAINS (TEXT + NAMED CHECK, not native ENUM)
-- ============================================================================
-- Decision (2026-07-03, migration 0003): FrigoLoco does NOT use native PostgreSQL
-- ENUM types. Each status/type column is plain TEXT guarded by a NAMED CHECK that
-- lists the allowed values (declared inline on the owning table below). Native
-- enums are painful to evolve (ALTER TYPE cannot run in every transaction, values
-- cannot be dropped/reordered) and leak the type name into every constraint/view
-- dependency; TEXT + CHECK is trivially editable and keeps the value list next to
-- the column. The allowed value sets:
--   users.role                 IN ('admin','ops_manager','warehouse','driver','finance')
--   purchase_orders.status     IN ('pending','received','cancelled')
--   dispatches.status          IN ('draft','saved','dispatched','reconciled')
--   stock_movements.movement_type IN ('po_receipt','dispatch','adjustment','cancellation_reversal')
--   weekly_menus.status        IN ('draft','active','archived')
--   restock_events.action      IN ('added','removed')
--   restock_events.tag_status  IN ('valid','unreliable','unrecognised')
--   dispatch_lines.source      IN ('forecast','manual')
--   alerts.alert_type          IN ('expiry','low_stock','below_target','negative_blocked','rfid_offline')

-- ============================================================================
-- SECTION 2 — IDENTITY & MASTER DATA (users, catalogue, clients, fridges)
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email           TEXT         NOT NULL UNIQUE,
    full_name       TEXT         NOT NULL,
    password_hash   TEXT         NOT NULL,
    role            TEXT         NOT NULL
                                 CONSTRAINT chk_users_role
                                 CHECK (role IN ('admin', 'ops_manager', 'warehouse', 'driver', 'finance')),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS suppliers (
    id                 INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name               TEXT         NOT NULL UNIQUE,
    email              TEXT,
    warehouse_address  TEXT,
    is_active          BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS categories (
    id                    INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                  TEXT         NOT NULL UNIQUE,
    display_order         INTEGER      NOT NULL UNIQUE,
    -- Fixed order in which categories print on driver delivery sheets (R8).
    dispatch_print_order  INTEGER      NOT NULL UNIQUE,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
    id               INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- TEXT on purpose: barcodes/product codes keep leading zeros.
    code             TEXT           NOT NULL UNIQUE,
    name             TEXT           NOT NULL,
    category_id      INTEGER        NOT NULL REFERENCES categories(id),
    supplier_id      INTEGER        REFERENCES suppliers(id),
    -- Money in minor units (cents), BIGINT — see header convention.
    purchase_price   BIGINT         NOT NULL DEFAULT 0 CHECK (purchase_price >= 0),
    sales_price      BIGINT         NOT NULL DEFAULT 0 CHECK (sales_price >= 0),
    -- VAT as a fraction (R5): 0.06 = 6 %.
    vat_rate         NUMERIC(6,4)   NOT NULL DEFAULT 0 CHECK (vat_rate >= 0 AND vat_rate < 1),
    -- NULLable: 218 products arrive from Husky without expiry days (backfill task).
    shelf_life_days  INTEGER        CHECK (shelf_life_days > 0),
    is_active        BOOLEAN        NOT NULL DEFAULT TRUE,
    -- Manual status override (D5): NULL follows Husky (is_active), a non-NULL
    -- value is user-forced and wins over sync. Sync NEVER writes this column.
    local_status     TEXT           CHECK (local_status IN ('inactive', 'cancelled')),
    husky_synced_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clients (
    id             INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           TEXT         NOT NULL,
    location       TEXT,
    workers_count  INTEGER      CHECK (workers_count >= 0),
    worker_type    TEXT,
    preferences    TEXT,
    notes          TEXT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fridges (
    id                     INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Husky device id, e.g. 'if-0001120'. Scripts join on friendlyName OR
    -- fridge.name inconsistently — both map to this one internal row.
    husky_id               TEXT         NOT NULL UNIQUE,
    husky_name             TEXT,
    friendly_name          TEXT         NOT NULL UNIQUE,
    client_id              INTEGER      REFERENCES clients(id),
    delivery_address       TEXT,
    delivery_instructions  TEXT,
    is_active              BOOLEAN      NOT NULL DEFAULT TRUE,
    -- Manual status override (D5): NULL follows Husky (is_active), a non-NULL
    -- value is user-forced and wins over sync. Sync NEVER writes this column.
    local_status           TEXT         CHECK (local_status IN ('inactive', 'cancelled')),
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Per-fridge sales-price overrides (briefing slide 24).
CREATE TABLE IF NOT EXISTS fridge_product_prices (
    fridge_id    INTEGER        NOT NULL REFERENCES fridges(id) ON DELETE CASCADE,
    product_id   INTEGER        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sales_price  BIGINT         NOT NULL CHECK (sales_price >= 0),  -- cents
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (fridge_id, product_id)
);

-- Forecast V2 columns C–E: per delivery weekday, the holiday-filter minimum
-- and how many days one delivery must cover (R1 inputs).
CREATE TABLE IF NOT EXISTS fridge_delivery_config (
    fridge_id      INTEGER   NOT NULL REFERENCES fridges(id) ON DELETE CASCADE,
    weekday        SMALLINT  NOT NULL CHECK (weekday BETWEEN 1 AND 7),  -- ISO: 1=Mon
    min_daily_qty  INTEGER   NOT NULL DEFAULT 0 CHECK (min_daily_qty >= 0),
    days_to_fill   INTEGER   NOT NULL CHECK (days_to_fill > 0),
    PRIMARY KEY (fridge_id, weekday)
);

CREATE TABLE IF NOT EXISTS client_fees (
    id              INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id       INTEGER        NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    yearly_fee      BIGINT         NOT NULL CHECK (yearly_fee >= 0),  -- cents
    contract_start  DATE           NOT NULL,
    contract_end    DATE,
    CHECK (contract_end IS NULL OR contract_end >= contract_start)
);

CREATE TABLE IF NOT EXISTS client_service_charges (
    id           INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id    INTEGER        NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    -- First day of the month the one-off charge belongs to.
    month        DATE           NOT NULL CHECK (month = date_trunc('month', month)::date),
    amount       BIGINT         NOT NULL,  -- cents
    description  TEXT           NOT NULL,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS client_interventions (
    id                 INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fridge_id          INTEGER      NOT NULL REFERENCES fridges(id) ON DELETE CASCADE,
    intervention_type  TEXT         NOT NULL,
    description        TEXT,
    occurred_at        TIMESTAMPTZ  NOT NULL,
    created_by         INTEGER      REFERENCES users(id),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Snacks & Drinks target-based replenishment (R3): to-restock = target − live stock.
CREATE TABLE IF NOT EXISTS product_targets (
    fridge_id   INTEGER      NOT NULL REFERENCES fridges(id) ON DELETE CASCADE,
    product_id  INTEGER      NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    target_qty  INTEGER      NOT NULL CHECK (target_qty >= 0),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (fridge_id, product_id)
);

-- Max units of a product one fridge may receive per dispatch (slide 8 caps).
CREATE TABLE IF NOT EXISTS menu_product_caps (
    fridge_id   INTEGER      NOT NULL REFERENCES fridges(id) ON DELETE CASCADE,
    product_id  INTEGER      NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    max_qty     INTEGER      NOT NULL CHECK (max_qty > 0),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (fridge_id, product_id)
);

-- ============================================================================
-- SECTION 3 — PURCHASE ORDERS & PER-YEAR ORDER NUMBERING (R4, R5)
-- ============================================================================

-- Per-year counter behind next_order_no(). ON CONFLICT ... DO UPDATE takes a
-- row lock on the year row, so concurrent PO creation serializes safely.
CREATE TABLE IF NOT EXISTS order_no_counters (
    year      INTEGER  PRIMARY KEY,
    last_seq  INTEGER  NOT NULL DEFAULT 0
);

CREATE OR REPLACE FUNCTION next_order_no()
RETURNS TEXT
LANGUAGE plpgsql
AS $$
-- R4: order numbers are 'YYYY-NNNNN', zero-padded, per-year sequence.
-- Concurrency-safe: the upsert row-locks the current year's counter row until
-- the calling transaction commits, so two concurrent POs can never draw the
-- same number (a rolled-back transaction leaves a gap, which is acceptable).
DECLARE
    current_year  INTEGER := EXTRACT(YEAR FROM CURRENT_DATE)::INTEGER;
    new_seq       INTEGER;
BEGIN
    INSERT INTO order_no_counters AS c (year, last_seq)
    VALUES (current_year, 1)
    ON CONFLICT (year)
    DO UPDATE SET last_seq = c.last_seq + 1
    RETURNING last_seq INTO new_seq;

    RETURN format('%s-%s', current_year, lpad(new_seq::TEXT, 5, '0'));
END;
$$;

CREATE TABLE IF NOT EXISTS purchase_orders (
    id                       INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_no                 TEXT           NOT NULL UNIQUE
                                            CHECK (order_no ~ '^\d{4}-\d{5}$'),
    supplier_id              INTEGER        NOT NULL REFERENCES suppliers(id),
    status                   TEXT           NOT NULL DEFAULT 'pending'
                                            CONSTRAINT chk_purchase_orders_status
                                            CHECK (status IN ('pending', 'received', 'cancelled')),
    order_date               DATE           NOT NULL DEFAULT CURRENT_DATE,
    expected_delivery_date   DATE           NOT NULL,
    delivery_address         TEXT,
    comment                  TEXT,
    -- R5: totals accumulate ex-VAT, VAT and incl-VAT separately.
    total_ex_vat             BIGINT         NOT NULL DEFAULT 0,  -- cents
    total_vat                BIGINT         NOT NULL DEFAULT 0,  -- cents
    total_incl_vat           BIGINT         NOT NULL DEFAULT 0,  -- cents
    created_by               INTEGER        REFERENCES users(id),
    created_at               TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ    NOT NULL DEFAULT now(),
    -- R4: delivery cannot precede the order date. ("No past dates" at creation
    -- time is an application/API rule — a table CHECK against CURRENT_DATE
    -- would wrongly reject historical rows migrated from Order History.)
    CHECK (expected_delivery_date >= order_date)
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id            INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_id         INTEGER        NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_id    INTEGER        NOT NULL REFERENCES products(id),
    qty_ordered   INTEGER        NOT NULL CHECK (qty_ordered > 0),
    qty_received  INTEGER        NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
    unit_price    BIGINT         NOT NULL CHECK (unit_price >= 0),  -- cents
    vat_rate      NUMERIC(6,4)   NOT NULL DEFAULT 0 CHECK (vat_rate >= 0 AND vat_rate < 1),
    UNIQUE (po_id, product_id)
);

-- ============================================================================
-- SECTION 4 — MENUS, FORECASTS, SCORES (R1, R2, R3)
-- ============================================================================

-- day_name (ISO weekday name) completes the (year, iso_week, day_name) natural
-- key the Forecast->Menu->Dispatch pipeline keys on (migration 0005, D2). The
-- '' default keeps the legacy week-level create path unique.
CREATE TABLE IF NOT EXISTS weekly_menus (
    id              INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    year            INTEGER      NOT NULL CHECK (year BETWEEN 2020 AND 2100),
    iso_week        INTEGER      NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
    day_name        TEXT         NOT NULL DEFAULT '',
    status          TEXT         NOT NULL DEFAULT 'draft'
                                 CONSTRAINT chk_weekly_menus_status
                                 CHECK (status IN ('draft', 'active', 'archived')),
    copied_from_id  INTEGER      REFERENCES weekly_menus(id),
    created_by      INTEGER      REFERENCES users(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_weekly_menus_year_week_day UNIQUE (year, iso_week, day_name)
);

CREATE TABLE IF NOT EXISTS menu_products (
    menu_id     INTEGER  NOT NULL REFERENCES weekly_menus(id) ON DELETE CASCADE,
    product_id  INTEGER  NOT NULL REFERENCES products(id),
    PRIMARY KEY (menu_id, product_id)
);

-- menu_lines: the per-fridge x product quantity grid a SAVED workflow menu
-- carries (migration 0005, D2). menu_products (membership only) is unchanged;
-- category_id is denormalised for the category-banded grid render (== products.category_id).
CREATE TABLE IF NOT EXISTS menu_lines (
    id           BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    menu_id      INTEGER  NOT NULL REFERENCES weekly_menus(id) ON DELETE CASCADE,
    fridge_id    INTEGER  NOT NULL REFERENCES fridges(id),
    product_id   INTEGER  NOT NULL REFERENCES products(id),
    category_id  INTEGER  NOT NULL REFERENCES categories(id),
    qty          INTEGER  NOT NULL CONSTRAINT chk_menu_lines_qty_nonneg CHECK (qty >= 0),
    CONSTRAINT uq_menu_lines_menu_fridge_product UNIQUE (menu_id, fridge_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_menu_lines_menu ON menu_lines (menu_id);
CREATE INDEX IF NOT EXISTS ix_menu_lines_product ON menu_lines (product_id);

-- model: extensible enum-style selector (only 'moving_average_3w' today).
-- is_saved: false = ephemeral /forecasts/run compute; true = the ONE persisted
-- forecast per (year, week, day). day_name mirrors delivery_date's ISO weekday
-- for saved runs. Natural key: delivery_date (bijective with year/week/day).
CREATE TABLE IF NOT EXISTS forecast_runs (
    id             INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    delivery_date  DATE         NOT NULL,
    model          TEXT         NOT NULL DEFAULT 'moving_average_3w'
                                CONSTRAINT chk_forecast_runs_model
                                CHECK (model IN ('moving_average_3w')),
    is_saved       BOOLEAN      NOT NULL DEFAULT false,
    day_name       TEXT,
    -- Snapshot of the parameters the run used: window weeks, scoring weights,
    -- per-category margins — keeps every run reproducible (R1).
    params         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_by     INTEGER      REFERENCES users(id)
);

-- Exactly one SAVED forecast per delivery_date (== per iso_year/week/day).
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_runs_saved_delivery_date
    ON forecast_runs (delivery_date) WHERE is_saved;

CREATE TABLE IF NOT EXISTS forecast_results (
    id            INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        INTEGER        NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
    fridge_id     INTEGER        NOT NULL REFERENCES fridges(id),
    category_id   INTEGER        NOT NULL REFERENCES categories(id),
    forecast_qty  NUMERIC(10,2)  NOT NULL CHECK (forecast_qty >= 0),
    valid_days    INTEGER        NOT NULL DEFAULT 0 CHECK (valid_days >= 0),
    holiday_days  INTEGER        NOT NULL DEFAULT 0 CHECK (holiday_days >= 0),
    UNIQUE (run_id, fridge_id, category_id)
);

CREATE TABLE IF NOT EXISTS product_scores (
    id            INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id    INTEGER       NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    period_end    DATE          NOT NULL,
    pct_sold      NUMERIC(7,4),
    review_score  NUMERIC(7,4),
    margin_score  NUMERIC(7,4),
    final_score   NUMERIC(7,4)  NOT NULL,
    sample_size   INTEGER       NOT NULL DEFAULT 0 CHECK (sample_size >= 0),
    computed_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (product_id, period_end)
);

CREATE TABLE IF NOT EXISTS fridge_product_scores (
    id            INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fridge_id     INTEGER       NOT NULL REFERENCES fridges(id) ON DELETE CASCADE,
    product_id    INTEGER       NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    period_end    DATE          NOT NULL,
    pct_sold      NUMERIC(7,4),
    review_score  NUMERIC(7,4),
    margin_score  NUMERIC(7,4),
    final_score   NUMERIC(7,4)  NOT NULL,
    sample_size   INTEGER       NOT NULL DEFAULT 0 CHECK (sample_size >= 0),
    computed_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (fridge_id, product_id, period_end)
);

-- ============================================================================
-- SECTION 5 — DISPATCH (R7, R8)
-- ============================================================================

CREATE TABLE IF NOT EXISTS dispatches (
    id             INTEGER          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    delivery_date  DATE             NOT NULL,
    iso_week       INTEGER          NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
    weekday        SMALLINT         NOT NULL CHECK (weekday BETWEEN 1 AND 7),  -- ISO: 1=Mon
    status         TEXT             NOT NULL DEFAULT 'draft'
                                    CONSTRAINT chk_dispatches_status
                                    CHECK (status IN ('draft', 'saved', 'dispatched', 'reconciled')),
    confirmed_by   INTEGER          REFERENCES users(id),
    confirmed_at   TIMESTAMPTZ,
    created_by     INTEGER          REFERENCES users(id),
    created_at     TIMESTAMPTZ      NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ      NOT NULL DEFAULT now(),
    -- Dispatched/reconciled batches must carry their confirmation stamp.
    CONSTRAINT chk_dispatches_confirmed_stamp
        CHECK (status NOT IN ('dispatched', 'reconciled') OR confirmed_at IS NOT NULL)
);

-- R7 batch identity: exactly one dispatch batch per delivery date. Saving a
-- day again REPLACES that batch's lines instead of creating a second batch.
CREATE UNIQUE INDEX IF NOT EXISTS uq_dispatches_delivery_date
    ON dispatches (delivery_date);

-- RANGE-partitioned monthly on delivery_date (migration 0004). delivery_date is
-- DENORMALISED from the parent dispatches row (immutable, never drifts) so it can
-- serve as the partition key. The partition key must be part of every unique key,
-- hence the composite PK (id, delivery_date) and the delivery_date-extended
-- natural key — mirrors the sales_events pattern. Partitions are created below in
-- SECTION 7 alongside the event-table partitions.
CREATE TABLE IF NOT EXISTS dispatch_lines (
    id                   INTEGER        GENERATED ALWAYS AS IDENTITY,
    dispatch_id          INTEGER        NOT NULL REFERENCES dispatches(id) ON DELETE CASCADE,
    fridge_id            INTEGER        NOT NULL REFERENCES fridges(id),
    product_id           INTEGER        NOT NULL REFERENCES products(id),
    delivery_date        DATE           NOT NULL,   -- partition key (== dispatches.delivery_date)
    qty                  INTEGER        NOT NULL
                                        CONSTRAINT chk_dispatch_lines_qty_positive CHECK (qty > 0),
    source               TEXT           NOT NULL DEFAULT 'manual'
                                        CONSTRAINT chk_dispatch_lines_source
                                        CHECK (source IN ('forecast', 'manual')),
    -- Price snapshots taken at confirm time — P&L must not drift when the
    -- catalogue price changes later.
    unit_purchase_price  BIGINT,        -- cents
    unit_sales_price     BIGINT,        -- cents
    vat_rate             NUMERIC(6,4)
                                        CONSTRAINT chk_dispatch_lines_vat_rate
                                        CHECK (vat_rate IS NULL OR (vat_rate >= 0 AND vat_rate < 1)),
    CONSTRAINT dispatch_lines_pkey PRIMARY KEY (id, delivery_date),
    -- Doubles as the (dispatch_id) access-path index: dispatch_id is the
    -- leading column, so no separate index on (dispatch_id) is needed.
    CONSTRAINT uq_dispatch_lines_dispatch_fridge_product
        UNIQUE (dispatch_id, fridge_id, product_id, delivery_date)
) PARTITION BY RANGE (delivery_date);

-- delivery_date is the partition key and MUST be supplied by the caller (it is
-- denormalised from the parent dispatch). A trigger cannot backfill it —
-- PostgreSQL rejects a NULL partition key during tuple routing, before any
-- BEFORE-INSERT trigger on the parent could run. The dispatch service sets
-- delivery_date = dispatch.delivery_date on every insert.

-- ============================================================================
-- SECTION 6 — STOCK LEDGER (append-only, non-negative — slide 24, R6)
-- ============================================================================

CREATE TABLE IF NOT EXISTS stock_movements (
    id                BIGINT               GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id        INTEGER              NOT NULL REFERENCES products(id),
    -- Signed quantity. Sign convention enforced per movement type below.
    qty               INTEGER              NOT NULL CHECK (qty <> 0),
    movement_type     TEXT                 NOT NULL
                                           CONSTRAINT chk_stock_movements_movement_type
                                           CHECK (movement_type IN ('po_receipt', 'dispatch', 'adjustment', 'cancellation_reversal')),
    po_line_id        INTEGER              REFERENCES purchase_order_lines(id),
    -- No FK: dispatch_lines is RANGE-partitioned (composite PK id+delivery_date),
    -- so a FK on id alone is impossible (migration 0004). The link is enforced by
    -- the application; the id value is still stored for joins.
    dispatch_line_id  INTEGER,
    reason            TEXT,
    created_by        INTEGER              REFERENCES users(id),
    created_at        TIMESTAMPTZ          NOT NULL DEFAULT now(),
    -- Sign conventions: receipts add, dispatches remove, cancellation
    -- reversals remove previously received stock, adjustments go either way.
    CONSTRAINT chk_movement_sign CHECK (
        (movement_type = 'po_receipt'            AND qty > 0) OR
        (movement_type = 'dispatch'              AND qty < 0) OR
        (movement_type = 'cancellation_reversal' AND qty < 0) OR
        (movement_type = 'adjustment')
    ),
    -- Manual adjustments always carry a reason (slide 9 / API rule).
    CONSTRAINT chk_adjustment_reason CHECK (
        movement_type <> 'adjustment'
        OR (reason IS NOT NULL AND btrim(reason) <> '')
    ),
    -- Receipts/reversals reference a PO line; dispatches reference a dispatch line.
    CONSTRAINT chk_movement_reference CHECK (
        (movement_type IN ('po_receipt', 'cancellation_reversal') AND po_line_id IS NOT NULL) OR
        (movement_type = 'dispatch'                               AND dispatch_line_id IS NOT NULL) OR
        (movement_type = 'adjustment')
    )
);

-- ---------------------------------------------------------------------------
-- NON-NEGOTIABLE (slide 24): stock can never go negative, enforced in the DB.
-- A per-product advisory lock serializes concurrent inserts for the same
-- product, so two simultaneous dispatches cannot both pass the balance check.
-- The API surfaces the raised error as HTTP 409 + a 'negative_blocked' alert.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforce_stock_non_negative()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    running_balance BIGINT;
BEGIN
    -- Transaction-scoped advisory lock keyed on the product: concurrent
    -- inserts for the same product serialize; different products don't block.
    PERFORM pg_advisory_xact_lock(hashtext('stock_movements'), NEW.product_id);

    SELECT COALESCE(SUM(qty), 0)
      INTO running_balance
      FROM stock_movements
     WHERE product_id = NEW.product_id;

    IF running_balance + NEW.qty < 0 THEN
        RAISE EXCEPTION
            'Stock non-negativity violation: product_id=% balance=% movement qty=% would give %',
            NEW.product_id, running_balance, NEW.qty, running_balance + NEW.qty
            USING ERRCODE = 'check_violation',
                  HINT = 'Physical warehouse stock can never go below zero (slide 24).';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_stock_non_negative ON stock_movements;
CREATE TRIGGER trg_stock_non_negative
    BEFORE INSERT ON stock_movements
    FOR EACH ROW
    EXECUTE FUNCTION enforce_stock_non_negative();

-- Append-only ledger: history is immutable. Corrections are made by inserting
-- compensating 'adjustment' / 'cancellation_reversal' rows, never by editing.
CREATE OR REPLACE FUNCTION block_stock_movement_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'stock_movements is append-only: % is not allowed. Insert a compensating movement instead.',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_stock_movements_append_only ON stock_movements;
CREATE TRIGGER trg_stock_movements_append_only
    BEFORE UPDATE OR DELETE ON stock_movements
    FOR EACH ROW
    EXECUTE FUNCTION block_stock_movement_mutation();

-- ============================================================================
-- SECTION 7 — RAW RFID EVENT STORE (partitioned; the 20–30M-row layer)
-- ============================================================================

-- One row per unit sold, from Husky GET /purchases. Prices stored RAW as the
-- Husky int64 minor units (cents) — no conversion at ingestion. Refunded sales
-- stay in (is_refunded = TRUE) because the
-- Excel logic counts them as sold; P&L nets them out (R10).
CREATE TABLE IF NOT EXISTS sales_events (
    id                BIGINT         GENERATED ALWAYS AS IDENTITY,
    husky_ref         TEXT           NOT NULL,
    fridge_id         INTEGER        NOT NULL REFERENCES fridges(id),
    product_id        INTEGER        NOT NULL REFERENCES products(id),
    sold_at           TIMESTAMPTZ    NOT NULL,
    unit_price        BIGINT         NOT NULL,           -- cents
    is_refunded       BOOLEAN        NOT NULL DEFAULT FALSE,
    discount_amount   BIGINT         NOT NULL DEFAULT 0,  -- cents
    -- Distinguishes FrigoLoco-provided discounts from customer credit (R10).
    discount_provider TEXT,
    synced_at         TIMESTAMPTZ    NOT NULL DEFAULT now(),
    -- Partition key must be part of the PK / unique keys on partitioned tables.
    PRIMARY KEY (id, sold_at),
    -- Idempotent sync upserts key on (husky_ref, sold_at).
    UNIQUE (husky_ref, sold_at)
) PARTITION BY RANGE (sold_at);

-- One row per ADDED/REMOVED tag event, from Husky GET /restock.
-- tag_status drives R9: 'unrecognised' excluded from added qty,
-- 'unreliable' tracked separately and excluded from totals.
CREATE TABLE IF NOT EXISTS restock_events (
    id           BIGINT          GENERATED ALWAYS AS IDENTITY,
    husky_ref    TEXT            NOT NULL,
    fridge_id    INTEGER         NOT NULL REFERENCES fridges(id),
    product_id   INTEGER         NOT NULL REFERENCES products(id),
    action       TEXT            NOT NULL
                                 CONSTRAINT chk_restock_events_action
                                 CHECK (action IN ('added', 'removed')),
    tag_status   TEXT            NOT NULL DEFAULT 'valid'
                                 CONSTRAINT chk_restock_events_tag_status
                                 CHECK (tag_status IN ('valid', 'unreliable', 'unrecognised')),
    occurred_at  TIMESTAMPTZ     NOT NULL,
    synced_at    TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (id, occurred_at),
    UNIQUE (husky_ref, occurred_at)
) PARTITION BY RANGE (occurred_at);

-- ---------------------------------------------------------------------------
-- Partition maintenance
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION create_event_partitions_for_month(month_start DATE)
RETURNS VOID
LANGUAGE plpgsql
AS $$
-- Creates the monthly partition of sales_events and restock_events covering
-- the month that contains month_start. Safe to call repeatedly (IF NOT EXISTS).
DECLARE
    part_from  DATE := date_trunc('month', month_start)::DATE;
    part_to    DATE := (date_trunc('month', month_start) + INTERVAL '1 month')::DATE;
    suffix     TEXT := to_char(part_from, 'YYYY_MM');
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS sales_events_%s PARTITION OF sales_events
         FOR VALUES FROM (%L) TO (%L)',
        suffix, part_from, part_to);
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS restock_events_%s PARTITION OF restock_events
         FOR VALUES FROM (%L) TO (%L)',
        suffix, part_from, part_to);
END;
$$;

-- dispatch_lines is RANGE-partitioned monthly on delivery_date (migration 0004).
-- Its partition maintenance mirrors the event tables' — same monthly cadence.
CREATE OR REPLACE FUNCTION create_dispatch_line_partition_for_month(month_start DATE)
RETURNS VOID
LANGUAGE plpgsql
AS $$
-- Creates the monthly dispatch_lines partition covering month_start (idempotent).
DECLARE
    part_from  DATE := date_trunc('month', month_start)::DATE;
    part_to    DATE := (date_trunc('month', month_start) + INTERVAL '1 month')::DATE;
    suffix     TEXT := to_char(part_from, 'YYYY_MM');
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS dispatch_lines_%s PARTITION OF dispatch_lines
         FOR VALUES FROM (%L) TO (%L)',
        suffix, part_from, part_to);
END;
$$;

CREATE OR REPLACE FUNCTION create_next_month_event_partitions()
RETURNS VOID
LANGUAGE plpgsql
AS $$
-- Scheduler hook: call monthly (e.g. from the APScheduler nightly job) to make
-- sure the current AND next month's partitions always exist ahead of inserts —
-- for sales_events, restock_events AND dispatch_lines.
DECLARE
    next_month DATE := (date_trunc('month', CURRENT_DATE) + INTERVAL '1 month')::DATE;
BEGIN
    PERFORM create_event_partitions_for_month(CURRENT_DATE);
    PERFORM create_event_partitions_for_month(next_month);
    PERFORM create_dispatch_line_partition_for_month(CURRENT_DATE);
    PERFORM create_dispatch_line_partition_for_month(next_month);
END;
$$;

-- Pre-create event partitions from 2025-01 (covers the 12+ month Husky backfill)
-- through 2027-01.
DO $$
DECLARE
    m DATE := DATE '2025-01-01';
BEGIN
    WHILE m <= DATE '2027-01-01' LOOP
        PERFORM create_event_partitions_for_month(m);
        m := (m + INTERVAL '1 month')::DATE;
    END LOOP;
END;
$$;

-- Pre-create dispatch_lines partitions 2025-01 .. 2027-12 (migration 0004).
DO $$
DECLARE
    m DATE := DATE '2025-01-01';
BEGIN
    WHILE m <= DATE '2027-12-01' LOOP
        PERFORM create_dispatch_line_partition_for_month(m);
        m := (m + INTERVAL '1 month')::DATE;
    END LOOP;
END;
$$;

-- Customer ratings from Husky GET /productreview. rating == 1 is positive,
-- anything else negative (R2 review score).
CREATE TABLE IF NOT EXISTS product_reviews (
    id           BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    husky_ref    TEXT         UNIQUE,
    product_id   INTEGER      NOT NULL REFERENCES products(id),
    fridge_id    INTEGER      REFERENCES fridges(id),
    -- Thumbs model: 1 = positive, -1/0 = negative (scoring treats <> 1 as
    -- negative). Live data is {-1, 1}; the ops test seeds 0 as a negative.
    rating       SMALLINT     NOT NULL
                              CONSTRAINT chk_product_reviews_rating CHECK (rating IN (-1, 0, 1)),
    reviewed_at  TIMESTAMPTZ  NOT NULL,
    synced_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ============================================================================
-- SECTION 8 — RECONCILIATION (R9)
-- ============================================================================

CREATE TABLE IF NOT EXISTS restock_verifications (
    id           INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dispatch_id  INTEGER      NOT NULL REFERENCES dispatches(id) ON DELETE CASCADE,
    run_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by   INTEGER      REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS restock_verification_lines (
    id               INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    verification_id  INTEGER        NOT NULL REFERENCES restock_verifications(id) ON DELETE CASCADE,
    fridge_id        INTEGER        NOT NULL REFERENCES fridges(id),
    product_id       INTEGER        NOT NULL REFERENCES products(id),
    dispatched_qty   INTEGER        NOT NULL DEFAULT 0 CHECK (dispatched_qty >= 0),
    added_qty        INTEGER        NOT NULL DEFAULT 0 CHECK (added_qty >= 0),
    -- UNRELIABLE tags: counted separately, excluded from diff totals (R9).
    unreliable_qty   INTEGER        NOT NULL DEFAULT 0 CHECK (unreliable_qty >= 0),
    diff_qty         INTEGER        NOT NULL DEFAULT 0,
    -- Valued at buy price (R9).
    diff_value       BIGINT         NOT NULL DEFAULT 0,  -- cents
    UNIQUE (verification_id, fridge_id, product_id)
);

-- ============================================================================
-- SECTION 9 — FINANCE, SETTINGS, ALERTS, AUDIT (R10–R12)
-- ============================================================================

CREATE TABLE IF NOT EXISTS weekly_financials (
    id                    INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    year                  INTEGER        NOT NULL CHECK (year BETWEEN 2020 AND 2100),
    iso_week              INTEGER        NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
    -- Manual weekly inputs (R10) — everything else is computed from events.
    catering_turnover     BIGINT         NOT NULL DEFAULT 0,  -- cents
    catering_food_cost    BIGINT         NOT NULL DEFAULT 0,  -- cents
    tgtg_turnover         BIGINT         NOT NULL DEFAULT 0,  -- cents
    logistics_cost        BIGINT         NOT NULL DEFAULT 0,  -- cents
    drops_count           INTEGER        NOT NULL DEFAULT 0 CHECK (drops_count >= 0),
    unsold_items          INTEGER        NOT NULL DEFAULT 0 CHECK (unsold_items >= 0),
    -- Manual per-week fridge count (Weekly View input). NULL = not entered.
    fridge_count          INTEGER        CHECK (fridge_count IS NULL OR fridge_count >= 0),
    remarks               TEXT,
    -- Fee snapshots: the rates in force when the week was closed, so later
    -- settings changes never rewrite history.
    pos_fee_pct_snapshot  NUMERIC(6,4)   NOT NULL DEFAULT 0.09,   -- fraction, NOT money
    rfid_fee_snapshot     BIGINT         NOT NULL DEFAULT 10,     -- cents (EUR 0.10)
    updated_by            INTEGER        REFERENCES users(id),
    created_at            TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ    NOT NULL DEFAULT now(),
    UNIQUE (year, iso_week)
);

CREATE TABLE IF NOT EXISTS settings (
    key          TEXT         PRIMARY KEY,
    value        JSONB        NOT NULL,
    description  TEXT,
    updated_by   INTEGER      REFERENCES users(id),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alerts (
    id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_type       TEXT         NOT NULL
                                  CONSTRAINT chk_alerts_alert_type
                                  CHECK (alert_type IN ('expiry', 'low_stock', 'below_target', 'negative_blocked', 'rfid_offline')),
    payload          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    status           TEXT         NOT NULL DEFAULT 'open'
                                  CHECK (status IN ('open', 'acknowledged', 'resolved')),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    acknowledged_by  INTEGER      REFERENCES users(id),
    acknowledged_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      INTEGER      REFERENCES users(id),
    action       TEXT         NOT NULL,
    entity       TEXT         NOT NULL,
    entity_id    TEXT,
    before_data  JSONB,
    after_data   JSONB,
    at           TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ============================================================================
-- SECTION 10 — STOCK BALANCES VIEW
-- ============================================================================
-- Excel rule (Refresh Stock And Ordered / R6), restated for the ledger design:
--   physical_qty  = SUM(stock_movements.qty)          -- what is in the warehouse
--   on_order_qty  = SUM(qty_ordered - qty_received)   -- over lines of PENDING POs
--                   (clamped at 0 per line; received/cancelled POs contribute 0)
--   available_qty = on_order_qty + physical_qty       -- the Excel "available"
-- "On order" comes from PO lines, NOT from movements — this is the deliberate
-- split between "on order" and "in warehouse" (spec Decision 2).
CREATE OR REPLACE VIEW v_stock_balances AS
WITH physical AS (
    SELECT sm.product_id,
           SUM(sm.qty) AS physical_qty
      FROM stock_movements sm
     GROUP BY sm.product_id
),
on_order AS (
    SELECT pol.product_id,
           SUM(GREATEST(pol.qty_ordered - pol.qty_received, 0)) AS on_order_qty
      FROM purchase_order_lines pol
      JOIN purchase_orders po ON po.id = pol.po_id
     WHERE po.status = 'pending'
     GROUP BY pol.product_id
)
SELECT p.id                                                          AS product_id,
       p.code                                                        AS product_code,
       p.name                                                        AS product_name,
       COALESCE(ph.physical_qty, 0)::BIGINT                          AS physical_qty,
       COALESCE(oo.on_order_qty, 0)::BIGINT                          AS on_order_qty,
       (COALESCE(oo.on_order_qty, 0) + COALESCE(ph.physical_qty, 0))::BIGINT AS available_qty
  FROM products p
  LEFT JOIN physical ph ON ph.product_id = p.id
  LEFT JOIN on_order oo ON oo.product_id = p.id;

-- ============================================================================
-- SECTION 11 — INDEXES
-- ============================================================================

-- Event queries: forecast window scans per fridge and per product.
CREATE INDEX IF NOT EXISTS ix_sales_events_fridge_sold_at
    ON sales_events (fridge_id, sold_at);
CREATE INDEX IF NOT EXISTS ix_sales_events_product_sold_at
    ON sales_events (product_id, sold_at);
CREATE INDEX IF NOT EXISTS ix_restock_events_fridge_occurred_at
    ON restock_events (fridge_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_restock_events_product_occurred_at
    ON restock_events (product_id, occurred_at);

-- Ledger balance computation per product (also serves the trigger's SUM).
CREATE INDEX IF NOT EXISTS ix_stock_movements_product_created
    ON stock_movements (product_id, created_at);

-- Dispatch access paths. (dispatch_id) alone is covered by the UNIQUE
-- (dispatch_id, fridge_id, product_id) constraint's leading column; these
-- serve the per-fridge sheets and per-product history lookups.
CREATE INDEX IF NOT EXISTS ix_dispatch_lines_fridge
    ON dispatch_lines (fridge_id);
CREATE INDEX IF NOT EXISTS ix_dispatch_lines_product
    ON dispatch_lines (product_id);

CREATE INDEX IF NOT EXISTS ix_purchase_orders_status_delivery
    ON purchase_orders (status, expected_delivery_date);
CREATE INDEX IF NOT EXISTS ix_purchase_order_lines_product
    ON purchase_order_lines (product_id);

CREATE INDEX IF NOT EXISTS ix_products_category
    ON products (category_id);
CREATE INDEX IF NOT EXISTS ix_products_supplier
    ON products (supplier_id);

CREATE INDEX IF NOT EXISTS ix_product_reviews_product_reviewed_at
    ON product_reviews (product_id, reviewed_at);

CREATE INDEX IF NOT EXISTS ix_alerts_open
    ON alerts (created_at)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS ix_audit_log_entity
    ON audit_log (entity, entity_id, at);

-- ============================================================================
-- SECTION 12 — TABLE COMMENTS (Excel artifact each table replaces)
-- ============================================================================

COMMENT ON TABLE users                      IS 'New (briefing slide 14): named accounts with roles — the shared workbook had no users or permissions.';
COMMENT ON TABLE suppliers                  IS 'Replaces SupplierInfoTable in Smart Fridge Forecasting Tool V5.xlsx.';
COMMENT ON TABLE categories                 IS 'Replaces the hardcoded category lists scattered across Office Scripts (10 in one script, 9 in another) — normalized here once, with the fixed dispatch print order (R8).';
COMMENT ON TABLE products                   IS 'Replaces the producttype API cache + Menu sheet header rows: the 540-product catalogue with prices, VAT and shelf life.';
COMMENT ON TABLE fridge_product_prices      IS 'New (slide 24): per-fridge sales-price overrides — Excel had a single price per product.';
COMMENT ON TABLE clients                    IS 'New (slide 13 client page): client master data; today only implicit in fridge naming.';
COMMENT ON TABLE fridges                    IS 'Replaces DispatchTemplate.xlsx header rows + Husky facility API data; maps both friendlyName and fridge.name join keys to one internal id.';
COMMENT ON TABLE fridge_delivery_config     IS 'Replaces Forecast V2 columns C–E: per-weekday minimum daily qty (holiday filter) and days-to-fill (R1 inputs).';
COMMENT ON TABLE client_fees                IS 'Replaces the Fee List sheet in Weekly & Monthly Return V2.xlsx (yearly client fee + contract dates, R12).';
COMMENT ON TABLE client_service_charges     IS 'Replaces the Service Additionals sheet in Weekly & Monthly Return V2.xlsx (one-off per-client monthly charges, R12).';
COMMENT ON TABLE client_interventions       IS 'New (slide 13): intervention log per fridge — no Excel equivalent existed.';
COMMENT ON TABLE product_targets            IS 'Replaces the Snacks & Drinks Target Map sheet (3,522 rows): target-based replenishment quantities per fridge x product (R3).';
COMMENT ON TABLE menu_product_caps          IS 'New (slide 8): max units of a product per fridge per dispatch.';
COMMENT ON TABLE order_no_counters          IS 'Helper for next_order_no(): per-year sequence behind the YYYY-NNNNN order numbers (R4). Replaces the max-existing-order-number scan in Create Purchase Order.osts.';
COMMENT ON TABLE purchase_orders            IS 'Replaces OrdersSummaryTable (Order View / Order History) in the Forecasting workbook.';
COMMENT ON TABLE purchase_order_lines       IS 'Replaces OrdersLineItemsTable in the Forecasting workbook.';
COMMENT ON TABLE weekly_menus               IS 'Replaces the weekly Menu sheet tabs (slide 6) in the Forecasting workbook.';
COMMENT ON TABLE menu_products              IS 'Replaces the Menu sheet product columns: which products are on a given week''s menu.';
COMMENT ON TABLE forecast_runs              IS 'Replaces each execution of Update Forecast.osts — a stored, reproducible run with its parameter snapshot.';
COMMENT ON TABLE forecast_results           IS 'Replaces the Forecast V2 sheet output block: per fridge x category forecast quantities.';
COMMENT ON TABLE product_scores             IS 'Replaces the Product Rating yearly scorecard sheet (R2), recomputed nightly.';
COMMENT ON TABLE fridge_product_scores      IS 'New (briefing slide 18): per-fridge product scores for the target dual 50/50 scoring model (R2 target model).';
COMMENT ON TABLE dispatches                 IS 'Replaces the Global Dispatch History batch key (ISO week, weekday, week start) + its summary table (R7). One batch per delivery date.';
COMMENT ON TABLE dispatch_lines             IS 'Replaces GlobalDispatchHistoryTable rows (20,692 and growing) — with price snapshots and no full-sheet backup copy on every save. RANGE-partitioned monthly on delivery_date (denormalised from dispatches; migration 0004).';
COMMENT ON TABLE stock_movements            IS 'Replaces the StockAndOrderedTable recompute with an append-only signed ledger: balance = SUM(qty), non-negativity enforced by trigger (slide 24), cancellations are explicit reversals (fixes the Excel cancel bug).';
COMMENT ON TABLE sales_events               IS 'Replaces the Husky /purchases pulls the scripts re-fetched on demand — the 20-30M-row store Excel could never hold. Monthly partitions on sold_at.';
COMMENT ON TABLE restock_events             IS 'Replaces the Husky /restock pulls: ADDED/REMOVED tag events feeding reconciliation (R9) and scoring denominators. Monthly partitions on occurred_at.';
COMMENT ON TABLE product_reviews            IS 'Replaces the Husky /productreview pulls feeding the review component of product scoring (R2).';
COMMENT ON TABLE restock_verifications      IS 'Replaces RestockVerificationTemplate.xlsx: one reconciliation run per dispatch (R9).';
COMMENT ON TABLE restock_verification_lines IS 'Replaces the RestockVerificationTemplate product-level diff rows: dispatched vs RFID-ADDED per fridge x product, UNRELIABLE tracked separately.';
COMMENT ON TABLE weekly_financials          IS 'Replaces the Weekly View manual inputs + WeeklySummaryDataTable in Weekly & Monthly Return V2.xlsx (R10); the 18 aggregate tables become queries over raw events.';
COMMENT ON TABLE settings                   IS 'Replaces the tunable cells scattered across both workbooks: scoring weights, forecast margins, POS %, RFID fee, alert thresholds.';
COMMENT ON TABLE alerts                     IS 'Replaces the Power Automate alert emails (slide 12): expiry, low stock, below target, negative-blocked, RFID offline.';
COMMENT ON TABLE audit_log                  IS 'New (slide 23): user + timestamp + before/after for every mutating action — Excel had no audit trail on saves.';

COMMENT ON VIEW v_stock_balances IS
    'Warehouse stock per product: physical_qty = SUM(ledger), on_order_qty = pending PO remainder, available_qty = on_order + physical (Excel Stock & Ordered rule, R6).';
COMMENT ON FUNCTION next_order_no() IS
    'Concurrency-safe YYYY-NNNNN order number from a row-locked per-year counter (R4).';
COMMENT ON FUNCTION create_event_partitions_for_month(DATE) IS
    'Creates the monthly sales_events/restock_events partitions covering the given month (idempotent).';
COMMENT ON FUNCTION create_dispatch_line_partition_for_month(DATE) IS
    'Creates the monthly dispatch_lines partition covering the given month (idempotent).';
COMMENT ON FUNCTION create_next_month_event_partitions() IS
    'Scheduler hook: ensures current and next month partitions exist for sales_events, restock_events and dispatch_lines.';

-- ============================================================================
-- SECTION 13 — SEED DATA
-- ============================================================================

-- The 10 product categories. display_order = the numeric prefix used across
-- the workbooks; dispatch_print_order = the fixed driver-sheet order (R8):
-- Warm -> Frozen Warm -> Warm Jar -> Cold/Salads -> Wraps -> Breakfast ->
-- Soup -> Desserts -> Drinks -> Snacks.
INSERT INTO categories (name, display_order, dispatch_print_order) VALUES
    ('1. Cold Dishes',          1,  4),
    ('2. Warm Dishes',          2,  1),
    ('3. Warm Dishes Jar',      3,  3),
    ('4. Wraps & Sandwiches',   4,  5),
    ('5. Breakfast & Granolas', 5,  6),
    ('6. Soup',                 6,  7),
    ('7. Desserts',             7,  8),
    ('8. Drinks',               8,  9),
    ('9. Snacks',               9, 10),
    ('10. Frozen Warm Dishes', 10,  2)
ON CONFLICT (name) DO NOTHING;

-- Tunable settings lifted from the workbook cells.
INSERT INTO settings (key, value, description) VALUES
    ('scoring_weights',
     '{"pct_sold": 0.62, "review": 0.05, "margin": 0.33}',
     'R2 product-score weights (Product Rating sheet cells).'),
    ('forecast_margins',
     '{"1. Cold Dishes": 0, "2. Warm Dishes": 0, "3. Warm Dishes Jar": 0,
       "4. Wraps & Sandwiches": 0, "5. Breakfast & Granolas": 0, "6. Soup": 0,
       "7. Desserts": 0, "8. Drinks": 0, "9. Snacks": 0,
       "10. Frozen Warm Dishes": 0}',
     'R1 per-category forecast margin % (fraction), user-tunable; defaults to 0.'),
    ('pos_fee_pct',
     '0.09',
     'R10 POS/software fee: 9% of sales (Return workbook Settings sheet).'),
    ('rfid_fee_eur',
     '10',
     'R10 RFID fee in CENTS (minor units): 10 = EUR 0.10 per item sold. Value is
      cents as of migration 0002 (2026-07-03); the key name is kept for continuity.'),
    ('expiry_alert_days',
     '2',
     'Alert when product expiry is within N days (configurable, default 2).'),
    ('menu_category_columns',
     '6',
     'Minimum product column slots per category in Menu/Dispatch grids')
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
