-- ============================================================================
-- Migration 0024 - bank holidays + gross / fridge-stock split per forecast cell
-- ============================================================================
-- bank_holidays: Belgian public holidays. The forecast drops them from the
-- selling days of the sales window and of the days a delivery must cover.
-- Seeded with 2026 and 2027; operators add later years from the Forecast page.
--
-- forecast_results.gross_qty / residual_units: the forecast before the
-- in-fridge stock deduction and the stock units deducted, so the page can show
-- "gross - fridge stock = net". NULL on runs computed before this migration.
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS bank_holidays (
    holiday_date  DATE  PRIMARY KEY,
    label         TEXT  NOT NULL CHECK (btrim(label) <> '')
);

INSERT INTO bank_holidays (holiday_date, label) VALUES
    ('2026-01-01', 'New Year''s Day'),
    ('2026-04-06', 'Easter Monday'),
    ('2026-05-01', 'Labour Day'),
    ('2026-05-14', 'Ascension Day'),
    ('2026-05-25', 'Whit Monday'),
    ('2026-07-21', 'Belgian National Day'),
    ('2026-08-15', 'Assumption Day'),
    ('2026-11-01', 'All Saints'' Day'),
    ('2026-11-11', 'Armistice Day'),
    ('2026-12-25', 'Christmas Day'),
    ('2027-01-01', 'New Year''s Day'),
    ('2027-03-29', 'Easter Monday'),
    ('2027-05-01', 'Labour Day'),
    ('2027-05-06', 'Ascension Day'),
    ('2027-05-17', 'Whit Monday'),
    ('2027-07-21', 'Belgian National Day'),
    ('2027-08-15', 'Assumption Day'),
    ('2027-11-01', 'All Saints'' Day'),
    ('2027-11-11', 'Armistice Day'),
    ('2027-12-25', 'Christmas Day')
ON CONFLICT (holiday_date) DO NOTHING;

ALTER TABLE forecast_results
    ADD COLUMN IF NOT EXISTS gross_qty NUMERIC(10,2) CHECK (gross_qty >= 0);
ALTER TABLE forecast_results
    ADD COLUMN IF NOT EXISTS residual_units INTEGER CHECK (residual_units >= 0);

COMMIT;
