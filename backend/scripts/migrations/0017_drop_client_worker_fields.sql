-- ============================================================================
-- Migration 0017 - drop clients.workers_count and clients.worker_type
-- ============================================================================
-- Neither column drives any logic and no client has a workers_count. The user
-- decided to remove both; preferences and notes stay.
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_workers_count_check;
ALTER TABLE clients DROP CONSTRAINT IF EXISTS chk_clients_workers_count_nonneg;
ALTER TABLE clients DROP COLUMN IF EXISTS workers_count;
ALTER TABLE clients DROP COLUMN IF EXISTS worker_type;

COMMIT;
