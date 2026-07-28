-- ============================================================================
-- Migration 0012 - fridge_stock: ensure the table exists, and capture per-unit
--                  expiry dates from the Husky /stock/current payload
-- ============================================================================
-- WHY (two things in one migration):
--
-- 1. ENSURE THE TABLE EXISTS. The base CREATE for fridge_stock lived only in
--    schema.sql; migration 0009 also creates it but SEEDS from stock_snapshots,
--    so on any database that never had stock_snapshots the 0009 seed fails and
--    fridge_stock ends up missing entirely (observed on the Railway DB - the
--    menu-allocation snacks/drinks branch, its only reader, would have failed).
--    This migration re-creates it IF NOT EXISTS with no dependency on
--    stock_snapshots, so a migrations-only database gets a working table.
--
-- 2. CAPTURE EXPIRY. The Husky GET /stock/current payload carries a real
--    per-unit (per-RFID-tag) expiry date (CurrentTag.expiryDate) which the app
--    already parses (app/husky/schemas.py StockTag.expiryDate) but the snapshot
--    job previously discarded, keeping only the unit COUNT. The expiry_dates
--    column stores the list of expiry timestamps for the units in each
--    (fridge, product) row. It feeds the forecast residual-stock deduction
--    (units still good through the coverage window) and the withdrawal list
--    (units expiring before the next delivery) - deck slide 5. fridge_stock.units
--    stays the authoritative unit count; expiry_dates may be NULL/shorter when
--    tags carry no expiry.
--
-- Idempotent: every statement is IF NOT EXISTS. Safe to re-run.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS fridge_stock (
    fridge_id    INTEGER      NOT NULL REFERENCES fridges(id),
    product_code TEXT         NOT NULL,
    -- NULLable: snapshots can arrive for products not yet in the catalogue.
    product_id   INTEGER      REFERENCES products(id),
    units        INTEGER      NOT NULL
                              CONSTRAINT chk_fridge_stock_units_nonneg
                              CHECK (units >= 0),
    -- Per-unit expiry timestamps captured from Husky CurrentTag.expiryDate.
    expiry_dates TIMESTAMPTZ[],
    -- One shared generation timestamp per snapshot run (mark-and-sweep).
    taken_at     TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (fridge_id, product_code)
);

CREATE INDEX IF NOT EXISTS ix_fridge_stock_product ON fridge_stock (product_id);

-- For databases where fridge_stock already existed (e.g. created by 0009 before
-- this column was introduced), add the column without touching existing rows.
ALTER TABLE fridge_stock
    ADD COLUMN IF NOT EXISTS expiry_dates TIMESTAMPTZ[];

COMMENT ON COLUMN fridge_stock.expiry_dates IS
    'Per-unit expiry timestamps from Husky CurrentTag.expiryDate; units stays the authoritative count. Feeds the forecast residual-stock deduction and the withdrawal list.';

COMMIT;
