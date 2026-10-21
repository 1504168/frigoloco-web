-- ============================================================================
-- Migration 0014 - four forecast methods
-- ============================================================================
-- The forecast page offers four methods, all using the same formula over a
-- different sales window before the delivery date:
--   moving_average_3w : the 21 days before delivery
--   moving_average_3m : the 91 days (13 weeks) before delivery
--   last_year_3w      : the 3-week window shifted back 52 weeks (364 days)
--   last_year_3m      : the 13-week window shifted back 52 weeks (364 days)
-- A 364-day shift keeps weekdays aligned with the delivery week.
--
-- Idempotent: drops and recreates the CHECK with the full list.
-- ============================================================================

BEGIN;

ALTER TABLE forecast_runs DROP CONSTRAINT IF EXISTS chk_forecast_runs_model;

ALTER TABLE forecast_runs
    ADD CONSTRAINT chk_forecast_runs_model
    CHECK (model IN (
        'moving_average_3w',
        'moving_average_3m',
        'last_year_3w',
        'last_year_3m'
    ));

COMMIT;
