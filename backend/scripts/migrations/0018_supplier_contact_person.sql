-- ============================================================================
-- Migration 0018 - supplier contact person (name + phone)
-- ============================================================================
-- The team calls the supplier's contact person when goods do not arrive.
-- Both columns are optional free text and local-only: the Husky catalogue sync
-- only creates suppliers by name and never writes them.
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_name TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_phone TEXT;

COMMIT;
