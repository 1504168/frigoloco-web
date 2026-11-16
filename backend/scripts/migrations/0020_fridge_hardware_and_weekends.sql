-- ============================================================================
-- Migration 0020 - fridge modem / SIM numbers and "active on weekends"
-- ============================================================================
-- modem_number and sim_card_number identify the fridge's 4G/5G connection for
-- support calls. active_on_weekends tells the forecast whether Saturday and
-- Sunday are selling days; it defaults to TRUE so every existing forecast stays
-- exactly as it is until someone marks a fridge as closed on weekends.
-- All three columns are local-only: the Husky catalogue sync never writes them.
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

ALTER TABLE fridges ADD COLUMN IF NOT EXISTS modem_number TEXT;
ALTER TABLE fridges ADD COLUMN IF NOT EXISTS sim_card_number TEXT;
ALTER TABLE fridges ADD COLUMN IF NOT EXISTS active_on_weekends BOOLEAN NOT NULL DEFAULT TRUE;

COMMIT;
