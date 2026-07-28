-- 0012_fridge_stock_expiry.sql
--
-- Capture per-unit (per-RFID-tag) expiry dates on fridge_stock so the forecast
-- can deduct residual in-fridge stock that is still good through the coverage
-- window, and so a withdrawal list can flag units expiring before the next
-- delivery (deck slide 5).
--
-- The Husky GET /stock/current payload already carries CurrentTag.expiryDate per
-- tag and the app parses it (app/husky/schemas.py StockTag.expiryDate); the
-- snapshot job previously discarded it, keeping only the unit count. This column
-- stores the list of expiry timestamps for the units in each (fridge, product)
-- row. It is NULL/short when tags carry no expiry; fridge_stock.units stays the
-- authoritative unit count.
--
-- Idempotent: safe to re-run.

ALTER TABLE fridge_stock
    ADD COLUMN IF NOT EXISTS expiry_dates TIMESTAMPTZ[];

COMMENT ON COLUMN fridge_stock.expiry_dates IS
    'Per-unit expiry timestamps from Husky CurrentTag.expiryDate; units stays the authoritative count.';
