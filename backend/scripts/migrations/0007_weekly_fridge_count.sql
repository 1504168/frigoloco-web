-- ============================================================================
-- Migration 0007 — weekly_financials.fridge_count (manual weekly input)
-- ============================================================================
-- Requirement (2026-07-03): the Weekly & Monthly Return workbook's "Weekly View"
-- carries a manual per-week fridge count alongside the other manual inputs
-- (catering turnover, logistics cost, drops, unsold items). It was missing from
-- the ported schema; add it so the weekly finance PUT/GET can round-trip it.
--
-- Nullable INTEGER (NULL = "not entered this week"), non-negative when present.
--
-- Idempotent: the column is added only when absent, and the NAMED CHECK
-- constraint is added only when absent (pg_constraint guard). Re-running is a
-- no-op.
-- ============================================================================

BEGIN;

ALTER TABLE weekly_financials ADD COLUMN IF NOT EXISTS fridge_count INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_weekly_financials_fridge_count_nonneg'
           AND conrelid = 'public.weekly_financials'::regclass
    ) THEN
        ALTER TABLE weekly_financials
            ADD CONSTRAINT chk_weekly_financials_fridge_count_nonneg
            CHECK (fridge_count IS NULL OR fridge_count >= 0);
    END IF;
END
$$;

COMMIT;
