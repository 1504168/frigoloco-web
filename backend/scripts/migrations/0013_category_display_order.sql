-- ============================================================================
-- Migration 0013 - category display_order from the numeric name prefix
-- ============================================================================
-- Category names carry their screen order as a numeric prefix ("1. Cold Dishes",
-- "10. Frozen Warm Dishes"). Husky sync appended new categories with
-- max(display_order) + 1, so later ones ("11. Baguettes", "2. Wraps & Buns")
-- landed after "Uncategorised" instead of at their prefix position.
--
-- Two categories legitimately share the "2." prefix, so display_order can no
-- longer be UNIQUE; the list endpoint breaks ties by name. "Uncategorised" is
-- pinned last. No category is merged, renamed or deleted.
--
-- Idempotent: re-running recomputes the same values.
-- ============================================================================

BEGIN;

ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_display_order_key;

UPDATE categories
SET display_order = substring(name FROM '^(\d+)\.')::int
WHERE name ~ '^\d+\.';

UPDATE categories
SET display_order = 999
WHERE name = 'Uncategorised';

COMMIT;
