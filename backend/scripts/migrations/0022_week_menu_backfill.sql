-- ============================================================================
-- Migration 0022 - week menus: one product list per ISO week (spec 0008)
-- ============================================================================
-- The week menu is the weekly_menus row with day_name = '' and its product
-- list is menu_products. This backfills both from the day menus saved so far:
--
--   1. every (year, iso_week) that has a day menu gets its week row;
--   2. a week row with NO products yet gets the distinct products of all that
--      week's saved day menus (menu_lines).
--
-- Rule 2 makes re-running a no-op: a week list edited after the first run is
-- never touched again. Day menus are not changed. No DDL.
-- ============================================================================

BEGIN;

INSERT INTO weekly_menus (year, iso_week, day_name, status)
SELECT DISTINCT day_menu.year, day_menu.iso_week, '', 'active'
FROM weekly_menus AS day_menu
WHERE day_menu.day_name <> ''
ON CONFLICT ON CONSTRAINT uq_weekly_menus_year_week_day DO NOTHING;

INSERT INTO menu_products (menu_id, product_id)
SELECT DISTINCT week_menu.id, line.product_id
FROM weekly_menus AS week_menu
JOIN weekly_menus AS day_menu
  ON day_menu.year = week_menu.year
 AND day_menu.iso_week = week_menu.iso_week
 AND day_menu.day_name <> ''
JOIN menu_lines AS line ON line.menu_id = day_menu.id
WHERE week_menu.day_name = ''
  AND NOT EXISTS (
      SELECT 1 FROM menu_products AS existing WHERE existing.menu_id = week_menu.id
  )
ON CONFLICT (menu_id, product_id) DO NOTHING;

COMMIT;
