-- ============================================================================
-- Migration 0016 - product_scores per scoring window (90 / 180 / 365 days)
-- ============================================================================
-- The Rating page lets the user pick a 90, 180 or 365 day window and press
-- Recompute. Scores are now stored per window so the page shows exactly what was
-- computed (including the new-product baseline). Existing rows were computed over
-- the fixed 365-day window, so they get window_days = 365.
--
-- The page also shows the raw counts behind each score, so sold_qty and the
-- positive / negative review counts are stored next to the score. They stay NULL
-- on rows computed before this migration. uses_new_product_baseline marks a row
-- whose final_score is the average of established products, not its own score.
--
-- Idempotent: safe to re-run.
-- ============================================================================

BEGIN;

ALTER TABLE product_scores
    ADD COLUMN IF NOT EXISTS window_days INTEGER NOT NULL DEFAULT 365,
    ADD COLUMN IF NOT EXISTS sold_qty INTEGER,
    ADD COLUMN IF NOT EXISTS positive_reviews INTEGER,
    ADD COLUMN IF NOT EXISTS negative_reviews INTEGER,
    ADD COLUMN IF NOT EXISTS uses_new_product_baseline BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE product_scores DROP CONSTRAINT IF EXISTS chk_product_scores_window_days;
ALTER TABLE product_scores
    ADD CONSTRAINT chk_product_scores_window_days CHECK (window_days > 0);

ALTER TABLE product_scores DROP CONSTRAINT IF EXISTS chk_product_scores_counts_nonneg;
ALTER TABLE product_scores
    ADD CONSTRAINT chk_product_scores_counts_nonneg CHECK (
        sold_qty >= 0
        AND positive_reviews >= 0
        AND negative_reviews >= 0
    );

ALTER TABLE product_scores DROP CONSTRAINT IF EXISTS product_scores_product_id_period_end_key;
ALTER TABLE product_scores DROP CONSTRAINT IF EXISTS uq_product_scores_product_period;
ALTER TABLE product_scores DROP CONSTRAINT IF EXISTS uq_product_scores_product_period_window;
ALTER TABLE product_scores
    ADD CONSTRAINT uq_product_scores_product_period_window
    UNIQUE (product_id, period_end, window_days);

CREATE INDEX IF NOT EXISTS ix_product_scores_window_period
    ON product_scores (window_days, period_end DESC);

COMMIT;
