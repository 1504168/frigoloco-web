-- ============================================================================
-- Migration 0010 - drop restock_verifications / restock_verification_lines
--                  (legacy R9 restock-verification tables)
-- ============================================================================
-- NOTE (2026-07-28): Restock verification (legacy R9) removed. Dispatched-vs-added
-- reconciliation will be re-implemented later as a DERIVED, period-level
-- (weekly/monthly) TOTAL report computed on demand from dispatch_lines (dispatched
-- qty) + restock_events (RFID action='added', tag_status='valid') joined on
-- (fridge_id, product_id) by date range - NOT stored per-dispatch tables, because
-- dispatch is one global batch per delivery_date with no per-dispatch granularity.
-- Value diffs at dispatch_lines.unit_purchase_price, fallback products.purchase_price.
--
-- The ORM models, the API router/schemas/service, and the frontend page that
-- backed these tables have all been removed; the tables themselves are the last
-- remnant and this migration drops them.
--
-- NOT YET APPLIED - dropping tables is destructive; apply via psql/psycopg2 as a
-- separate approved step. Child table (restock_verification_lines) is dropped
-- first so its FK to the parent does not block the parent drop.
--
-- Idempotent: DROP TABLE IF EXISTS is a no-op when the table is already gone.
-- ============================================================================

BEGIN;

DROP TABLE IF EXISTS restock_verification_lines;
DROP TABLE IF EXISTS restock_verifications;

COMMIT;
