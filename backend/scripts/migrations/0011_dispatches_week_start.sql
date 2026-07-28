-- ============================================================================
-- Migration 0011 - add generated week_start column to dispatches
-- ============================================================================
-- Adds `week_start DATE` to the `dispatches` batch header: the Monday of the
-- batch's ISO week. It is a STORED generated column derived purely from
-- delivery_date, so it can never drift and needs no backfill or trigger -
-- Postgres computes it for every existing and future row automatically.
--
-- ISODOW: Mon=1..Sun=7, so week_start = delivery_date - (ISODOW - 1) days.
-- This mirrors the same definition now in architecture/database/schema.sql, so a
-- fresh database created from schema.sql gets an identical column WITHOUT running
-- this migration; this ALTER exists only to bring an already-populated live DB
-- into line.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS is a no-op when the column already exists.
-- Non-destructive (adds a derived column only), safe to apply anytime.
-- ============================================================================

BEGIN;

ALTER TABLE dispatches
    ADD COLUMN IF NOT EXISTS week_start DATE
    GENERATED ALWAYS AS (delivery_date - (EXTRACT(ISODOW FROM delivery_date)::int - 1)) STORED;

COMMIT;
