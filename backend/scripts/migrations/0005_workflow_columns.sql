-- ============================================================================
-- Migration 0005 - Week/day workflow natural keys + menu grid storage (D2)
-- ============================================================================
--
-- WHY: The Forecast -> Menu -> Dispatch pipeline keys every stage on
-- (iso_year, week_no, day_name) with save / load-saved / overwrite-confirm
-- semantics (WORKORDER-workflow-rework.md, D2). The pre-D2 schema could not
-- express this:
--
--   * forecast_runs had no "saved" concept and no model selector - every run
--     was an ephemeral compute. D2 wants POST /forecasts/run to compute only
--     and POST /forecasts/save to persist ONE saved forecast per key.
--   * weekly_menus was keyed per (year, iso_week) with no day - D2 makes the
--     menu a per-delivery-day artifact, and menu_products stored only which
--     products are on a menu, with NO fridge x product quantity grid.
--   * dispatches already carry a UNIQUE delivery_date, and delivery_date
--     bijects to (iso_year, week_no, day_name) via ISO calendar, so dispatches
--     need NO new column - the service derives delivery_date from the key.
--
-- NATURAL-KEY NOTE: a calendar date maps to exactly one (iso_year, iso_week,
-- iso_weekday) and vice versa, so `delivery_date` IS the (year, week, day)
-- natural key for forecast_runs and dispatches. weekly_menus keeps
-- (year, iso_week) columns and gains an explicit `day_name` to complete its
-- natural key (it has no date column).
--
-- Idempotent: guarded with IF [NOT] EXISTS / catalog checks so re-running is a
-- no-op. Applied live via scripts/apply_migration.py; schema.sql updated to match.
-- No native PG enums (text + CHECK per the 2026-07-03 decision).

BEGIN;

-- ---------------------------------------------------------------------------
-- forecast_runs: model selector + saved flag + explicit day_name
-- ---------------------------------------------------------------------------
ALTER TABLE forecast_runs
    ADD COLUMN IF NOT EXISTS model TEXT NOT NULL DEFAULT 'moving_average_3w';

-- Extensible enum-style string: only one model today; future models extend the
-- CHECK list (text + CHECK, never a native PG enum).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_forecast_runs_model'
    ) THEN
        ALTER TABLE forecast_runs
            ADD CONSTRAINT chk_forecast_runs_model
            CHECK (model IN ('moving_average_3w'));
    END IF;
END $$;

ALTER TABLE forecast_runs
    ADD COLUMN IF NOT EXISTS is_saved BOOLEAN NOT NULL DEFAULT false;

-- Denormalised ISO weekday name of delivery_date (Monday..Sunday). Kept in sync
-- by the service on every saved run; NULL for legacy/ephemeral compute rows.
ALTER TABLE forecast_runs
    ADD COLUMN IF NOT EXISTS day_name TEXT;

-- Exactly one SAVED forecast per delivery_date (== per iso_year/week/day). Draft
-- (is_saved=false) compute rows are unconstrained so /forecasts/run stays cheap.
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_runs_saved_delivery_date
    ON forecast_runs (delivery_date) WHERE is_saved;

-- ---------------------------------------------------------------------------
-- weekly_menus: per-day natural key
-- ---------------------------------------------------------------------------
-- Default '' keeps the legacy (year, iso_week)-only create path unique: a
-- week-level menu is (year, week, '') while a workflow menu is (year, week,
-- 'Wednesday'). Non-empty CHECK is intentionally NOT added so '' stays legal.
ALTER TABLE weekly_menus
    ADD COLUMN IF NOT EXISTS day_name TEXT NOT NULL DEFAULT '';

-- Swap UNIQUE(year, iso_week) -> UNIQUE(year, iso_week, day_name).
ALTER TABLE weekly_menus DROP CONSTRAINT IF EXISTS weekly_menus_year_iso_week_key;
ALTER TABLE weekly_menus DROP CONSTRAINT IF EXISTS uq_weekly_menus_year_week;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_weekly_menus_year_week_day'
    ) THEN
        ALTER TABLE weekly_menus
            ADD CONSTRAINT uq_weekly_menus_year_week_day
            UNIQUE (year, iso_week, day_name);
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- menu_lines: the fridge x product quantity grid a saved menu carries
-- ---------------------------------------------------------------------------
-- menu_products (which products are ON a menu) is unchanged; menu_lines adds the
-- per-fridge quantities the D2 grid needs. category_id is denormalised for the
-- category-banded grid render (WORKORDER D4) and always equals products.category_id.
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

COMMIT;
