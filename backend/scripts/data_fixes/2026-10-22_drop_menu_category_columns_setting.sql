-- Remove the retired 'menu_category_columns' setting.
-- The Menu and Dispatch grids no longer pad categories with empty product slots,
-- so nothing reads this value. Safe to run more than once.
BEGIN;

SELECT count(*) AS rows_before FROM settings WHERE key = 'menu_category_columns';

DELETE FROM settings WHERE key = 'menu_category_columns';

SELECT count(*) AS rows_after FROM settings WHERE key = 'menu_category_columns';

COMMIT;
