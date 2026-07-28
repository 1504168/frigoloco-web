-- ============================================================================
-- Migration 0010 - retain extra Husky product fields (store-only)
-- ============================================================================
-- WHY: the catalogue / price / review syncs were discarding several fields the
-- Husky API already returns. They cost nothing extra to fetch and are useful to
-- keep for future features:
--   * /producttype        -> description, currencyCode, priceExSurcharges
--   * /fridgeproductprice  -> priceExSurcharges, vat, currencyCode
--   * /productreview       -> the free-text review, reviewer email, purchase id
--                             + date, category, and the RFID tag identity
--                             (tagId / epc / reference)
--
-- This migration only ADDS columns and populates nothing retroactively: every
-- column is NULLable (the fields are optional in the vendor payload and existing
-- rows never carried them), and the sync mappers fill them on the next run.
--
-- Money is stored RAW as BIGINT minor units (cents), matching the Husky int64
-- contract (NO /100 at ingestion); VAT is a NUMERIC fraction (0.06 = 6%), like
-- products.vat_rate. These are Husky-owned columns, so the sync ownership
-- allowlist (_ALLOWED_UPDATE_COLUMNS) is extended in the same change.
--
-- Idempotent: every ADD COLUMN is IF NOT EXISTS. Re-running is a no-op.
-- Independent of migration 0009 (which touches fridge_stock, a different table).
-- ============================================================================

BEGIN;

-- products: description, currency, price before POS/RFID surcharges ----------
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS description         TEXT,
    ADD COLUMN IF NOT EXISTS currency_code       TEXT,
    ADD COLUMN IF NOT EXISTS price_ex_surcharges BIGINT
        CONSTRAINT chk_products_price_ex_surcharges_nonneg
        CHECK (price_ex_surcharges >= 0);

-- fridge_product_prices: the per-fridge equivalents of the product extras -----
ALTER TABLE fridge_product_prices
    ADD COLUMN IF NOT EXISTS price_ex_surcharges BIGINT
        CONSTRAINT chk_fridge_product_prices_ex_surcharges_nonneg
        CHECK (price_ex_surcharges >= 0),
    ADD COLUMN IF NOT EXISTS vat_rate            NUMERIC(6,4)
        CONSTRAINT chk_fridge_product_prices_vat_fraction
        CHECK (vat_rate >= 0 AND vat_rate < 1),
    ADD COLUMN IF NOT EXISTS currency_code       TEXT;

-- product_reviews: keep the full review payload, not just the thumbs rating ---
ALTER TABLE product_reviews
    ADD COLUMN IF NOT EXISTS review_text       TEXT,
    ADD COLUMN IF NOT EXISTS reviewer_email    TEXT,
    ADD COLUMN IF NOT EXISTS purchase_id       TEXT,
    ADD COLUMN IF NOT EXISTS purchased_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS review_category   TEXT,
    ADD COLUMN IF NOT EXISTS tag_id            TEXT,
    ADD COLUMN IF NOT EXISTS epc               TEXT,
    ADD COLUMN IF NOT EXISTS product_reference TEXT;

COMMIT;
