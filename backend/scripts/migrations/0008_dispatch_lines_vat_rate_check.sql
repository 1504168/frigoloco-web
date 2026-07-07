-- ============================================================================
-- Migration 0008 — dispatch_lines.vat_rate [0,1) CHECK
-- ============================================================================
-- WHY (REWORK-VALIDATION residual #5): the work order requires every VAT-rate
-- fraction column to be bounded to [0, 1). products.vat_rate and
-- purchase_order_lines.vat_rate already carry that CHECK, but
-- dispatch_lines.vat_rate was left unbounded, so a bad snapshot (e.g. 6.0 for
-- "6%" instead of 0.06) could be written. Add the same named CHECK for parity.
--
-- vat_rate is NULLable (NULL = "no price snapshot taken yet"), so the constraint
-- permits NULL and otherwise requires 0 <= vat_rate < 1.
--
-- dispatch_lines is RANGE-partitioned; a CHECK added to the partitioned parent
-- is inherited by every existing and future partition automatically.
--
-- Idempotent: the NAMED CHECK is added only when absent (pg_constraint guard on
-- the parent relation). Re-running is a no-op.
-- ============================================================================

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_dispatch_lines_vat_rate'
           AND conrelid = 'public.dispatch_lines'::regclass
    ) THEN
        ALTER TABLE dispatch_lines
            ADD CONSTRAINT chk_dispatch_lines_vat_rate
            CHECK (vat_rate IS NULL OR (vat_rate >= 0 AND vat_rate < 1));
    END IF;
END
$$;

COMMIT;
