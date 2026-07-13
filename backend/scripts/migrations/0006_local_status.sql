-- ============================================================================
-- Migration 0006 - Manual status override (local_status) on products & fridges
-- ============================================================================
-- Requirement (work-order D5, 2026-07-03): fridge + product data auto-syncs
-- from Husky, but a user's manual status marking must survive every sync.
--
-- Adds a nullable ``local_status`` column to both ``products`` and ``fridges``:
--   * NULL              -> follow Husky (is_active TRUE=active / FALSE=inactive);
--   * 'inactive'        -> user-forced inactive, wins over Husky;
--   * 'cancelled'       -> user-forced cancelled, wins over Husky.
-- Sync NEVER writes this column (field-ownership contract in
-- ``app/husky/sync.py``): it is local-owned. Effective activity =
-- local_status when set, else the Husky-derived is_active flag.
--
-- Idempotent: the column is added only when absent, and the NAMED CHECK
-- constraint is added only when absent (pg_constraint guard). Re-running is a
-- no-op.
-- ============================================================================

BEGIN;

-- products.local_status ------------------------------------------------------
ALTER TABLE products ADD COLUMN IF NOT EXISTS local_status TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_products_local_status_values'
           AND conrelid = 'public.products'::regclass
    ) THEN
        ALTER TABLE products
            ADD CONSTRAINT chk_products_local_status_values
            CHECK (local_status IN ('inactive', 'cancelled'));
    END IF;
END
$$;

-- fridges.local_status -------------------------------------------------------
ALTER TABLE fridges ADD COLUMN IF NOT EXISTS local_status TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_fridges_local_status_values'
           AND conrelid = 'public.fridges'::regclass
    ) THEN
        ALTER TABLE fridges
            ADD CONSTRAINT chk_fridges_local_status_values
            CHECK (local_status IN ('inactive', 'cancelled'));
    END IF;
END
$$;

COMMIT;
