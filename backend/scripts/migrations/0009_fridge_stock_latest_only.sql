-- ============================================================================
-- Migration 0009 - fridge_stock: latest-only in-fridge stock (replaces the
--                  stock_snapshots append-only log)
-- ============================================================================
-- WHY: ``stock_snapshots`` was an append-only time series written every 15 min
-- by the snapshot_stock cron (Husky ``GET /stock/current``). It has exactly ONE
-- reader - the menu allocation engine - which only ever reads the NEWEST row
-- per (fridge, product) to compute ``restock = max(target_qty - live, 0)``.
-- Nothing reads the history: no API endpoint, no frontend, no report. The log
-- therefore grows forever (fridges x products x 96 writes/day) to serve a
-- single "current value" lookup that a DISTINCT ON has to scan for.
--
-- Decision: keep only the latest known state - one row per (fridge, product) -
-- and let the snapshot job UPSERT into it. Stock history is not needed; if it
-- ever is, it belongs in a purpose-built rollup, not in the hot read path.
--
-- SEMANTICS: the snapshot job is MARK-AND-SWEEP, SCOPED TO THE FRIDGES IT
-- REPORTED ON. Every run stamps one shared ``taken_at`` on the rows it upserts,
-- then deletes the older-``taken_at`` rows of those fridges only - so for a
-- reported fridge the table mirrors the vendor response exactly (no orphan rows
-- for products pulled out of it, a missing row means live = 0), while a fridge
-- ABSENT from the payload (RFID reader offline, or a partial vendor response)
-- keeps its rows with their OLD ``taken_at``. Sweeping globally would wipe those
-- fridges, and the allocation engine would read them as empty and over-dispatch
-- every one of them to full target. Each fridge's ``taken_at`` generation is what
-- readers use to decide whether that fridge's stock is trustworthy (> 2h old =>
-- not reached; the forecast still uses the last-known units but flags the line).
--
-- NOT warehouse stock: warehouse quantities live in the stock_movements ledger
-- and are read through ``v_stock_balances``. This table is in-FRIDGE stock.
--
-- PRIMARY KEY is (fridge_id, product_code), NOT product_id: product_id is
-- NULLable because a snapshot can arrive for a product that is not in the
-- catalogue yet, and a NULLable column cannot carry the identity of the row.
--
-- stock_snapshots is deliberately NOT dropped here. Dropping it is a separate,
-- explicit step the user will approve once the new table has been observed in
-- production. This migration only seeds the new table from it.
--
-- Idempotent: CREATE TABLE / CREATE INDEX are IF NOT EXISTS, and the seed is an
-- ON CONFLICT DO NOTHING insert. Re-running is a no-op.
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
    taken_at     TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (fridge_id, product_code)
);

CREATE INDEX IF NOT EXISTS ix_fridge_stock_product ON fridge_stock (product_id);

-- Seed from the newest existing snapshot row per (fridge_id, product_code) so
-- no functional data is lost when the allocation engine switches readers.
-- Note: the seeded rows carry MIXED taken_at values (one per fridge x product),
-- unlike the single generation a real mark-and-sweep run produces. The first
-- snapshot_stock run after this migration normalises that (and sweeps away any
-- product that is no longer in its fridge).
INSERT INTO fridge_stock (fridge_id, product_code, product_id, units, taken_at)
SELECT DISTINCT ON (fridge_id, product_code)
       fridge_id, product_code, product_id, units, taken_at
  FROM stock_snapshots
 ORDER BY fridge_id, product_code, taken_at DESC
    ON CONFLICT (fridge_id, product_code) DO NOTHING;

COMMENT ON TABLE fridge_stock IS
    'Latest known in-fridge stock from Husky GET /stock/current - one row per fridge x product, NOT a time series. Mark-and-sweep SCOPED to the fridges each run reported on: the run stamps one shared taken_at and deletes only those fridges'' older rows, so a reported fridge mirrors the vendor response exactly (missing row = not in that fridge) while a fridge absent from the payload keeps its rows with an OLD taken_at - the signal readers use to flag it stale (> 2h). Read by the menu allocation engine for target-based replenishment (restock = max(target_qty - units, 0)). Warehouse stock is a different thing entirely - see v_stock_balances.';

COMMIT;
