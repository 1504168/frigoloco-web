-- ============================================================================
-- Migration 0015 - forecast margins keyed by category id
-- ============================================================================
-- settings.forecast_margins was keyed by category NAME, and the names drifted
-- (Husky sync renamed and added categories), so most margins no longer matched
-- any category. Re-key it as {"<category_id>": margin} for every category:
-- a category whose current name matches an old key keeps that margin, every
-- other category gets 0. Category renames can no longer orphan a margin.
--
-- Idempotent: only runs while some key is not a plain category id.
-- ============================================================================

BEGIN;

UPDATE settings
SET value = (
        SELECT COALESCE(
            jsonb_object_agg(
                categories.id::text,
                COALESCE(settings.value -> categories.name, '0'::jsonb)
            ),
            '{}'::jsonb
        )
        FROM categories
    ),
    description = 'R1 per-category forecast margin (fraction) keyed by category id; '
                  'missing categories use 0.',
    updated_at = now()
WHERE key = 'forecast_margins'
  AND EXISTS (
        SELECT 1
        FROM jsonb_object_keys(settings.value) AS margin_key
        WHERE margin_key !~ '^\d+$'
  );

COMMIT;
