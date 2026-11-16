-- ============================================================================
-- Migration 0025 - Husky fridge status, fridge preferences, product minimum
-- stock and product print order
-- ============================================================================
-- fridges.husky_status keeps the raw Husky fridge status (LIVE, SHIPPED,
-- END_OF_LIFE, ...). The catalogue sync now sets is_active = (status = 'LIVE')
-- instead of TRUE for every fridge in the feed; local_status still wins.
-- fridges.preferences is a free-text note about the site (what they like or
-- refuse), shown next to the fridge in the planning grids. Local-only.
-- products.min_stock_qty is the warehouse minimum: below it the hourly
-- low-stock job opens a low_stock alert. NULL = no minimum. Local-only.
-- products.print_order is the position of the product on the printed dispatch
-- sheet inside its category. NULL = after the numbered products. Local-only.
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

ALTER TABLE fridges ADD COLUMN IF NOT EXISTS husky_status TEXT;
ALTER TABLE fridges ADD COLUMN IF NOT EXISTS preferences TEXT;

ALTER TABLE products ADD COLUMN IF NOT EXISTS min_stock_qty INTEGER;
ALTER TABLE products ADD COLUMN IF NOT EXISTS print_order INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_products_min_stock_qty_nonneg'
    ) THEN
        ALTER TABLE products
            ADD CONSTRAINT chk_products_min_stock_qty_nonneg CHECK (min_stock_qty >= 0);
    END IF;
END $$;

COMMIT;
