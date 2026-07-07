-- ============================================================================
-- Migration 0003 — Native PG ENUM types -> TEXT + NAMED CHECK constraints
-- ============================================================================
-- Decision (2026-07-03, user): drop native PostgreSQL ENUM types entirely. Every
-- former enum column becomes plain TEXT guarded by a NAMED CHECK listing the
-- allowed values. Native enums are painful to evolve (ALTER TYPE cannot run in
-- every transaction, values cannot be dropped/reordered), and they leak the type
-- name into every constraint/view dependency. TEXT + CHECK is trivially editable.
--
-- Idempotent: each column conversion checks information_schema for its CURRENT
-- data_type and only alters while it is still 'USER-DEFINED'. CHECK constraints
-- are added only when absent (pg_constraint guard). DROP TYPE ... IF EXISTS and
-- DROP CONSTRAINT ... IF EXISTS make re-runs a no-op.
--
-- Order of operations (dependencies force this):
--   1. Drop v_stock_balances (depends on purchase_orders.status).
--   2. Drop the multi-column CHECKs that embed enum casts (they pin the type
--      and would block DROP TYPE).
--   3. Convert every enum column -> text + add its value CHECK.
--   4. Recreate the multi-column CHECKs with TEXT literals, NAMED to match the
--      ORM models.
--   5. Recreate v_stock_balances.
--   6. Additional NAMED CHECK from the datatype/CHECK review.
--   7. DROP the now-orphaned enum TYPES.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Guarded helpers (pg_temp: dropped automatically at session end).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pg_temp.add_check(
    p_table text,
    p_name  text,
    p_expr  text
) RETURNS void
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = p_name
           AND conrelid = format('public.%I', p_table)::regclass
    ) THEN
        EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (%s)',
                       p_table, p_name, p_expr);
        RAISE NOTICE 'migration 0003: added CHECK % on %', p_name, p_table;
    ELSE
        RAISE NOTICE 'migration 0003: CHECK % on % already present', p_name, p_table;
    END IF;
END;
$fn$;

CREATE OR REPLACE FUNCTION pg_temp.enum_col_to_text(
    p_table   text,
    p_col     text,
    p_check   text,       -- CHECK constraint name to add
    p_allowed text[],     -- allowed string values
    p_default text        -- new TEXT default literal, or NULL for no default
) RETURNS void
LANGUAGE plpgsql
AS $fn$
DECLARE
    cur_type     text;
    allowed_list text;
BEGIN
    SELECT data_type INTO cur_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name   = p_table
       AND column_name  = p_col;

    IF cur_type IS NULL THEN
        RAISE NOTICE 'migration 0003: %.% not found — skipped', p_table, p_col;
        RETURN;
    END IF;

    IF cur_type = 'USER-DEFINED' THEN
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I DROP DEFAULT', p_table, p_col);
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE text USING %I::text',
                       p_table, p_col, p_col);
        IF p_default IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN %I SET DEFAULT %L',
                           p_table, p_col, p_default);
        END IF;
        RAISE NOTICE 'migration 0003: converted %.% -> text', p_table, p_col;
    ELSE
        RAISE NOTICE 'migration 0003: %.% already %, skipping type change',
                     p_table, p_col, cur_type;
    END IF;

    -- Build "col IN ('a', 'b', ...)" and add the NAMED CHECK if absent.
    SELECT string_agg(quote_literal(v), ', ') INTO allowed_list
      FROM unnest(p_allowed) AS v;
    PERFORM pg_temp.add_check(p_table, p_check, format('%I IN (%s)', p_col, allowed_list));
END;
$fn$;

-- ---------------------------------------------------------------------------
-- 1. Drop the view that depends on purchase_orders.status.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_stock_balances;

-- ---------------------------------------------------------------------------
-- 2. Drop the multi-column CHECKs whose definitions embed enum-type casts.
--    (Auto-named ones from schema.sql + any already-renamed variants.)
-- ---------------------------------------------------------------------------
ALTER TABLE dispatches      DROP CONSTRAINT IF EXISTS dispatches_check;
ALTER TABLE dispatches      DROP CONSTRAINT IF EXISTS chk_dispatches_confirmed_stamp;
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS chk_movement_sign;
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS chk_movement_reference;
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS chk_adjustment_reason;

-- ---------------------------------------------------------------------------
-- 3. Convert every enum-typed column -> text + NAMED value CHECK.
--    (restock_events is partitioned; altering the parent cascades to children.)
-- ---------------------------------------------------------------------------
SELECT pg_temp.enum_col_to_text('users',           'role',          'chk_users_role',
        ARRAY['admin','ops_manager','warehouse','driver','finance'],           NULL);
SELECT pg_temp.enum_col_to_text('purchase_orders', 'status',        'chk_purchase_orders_status',
        ARRAY['pending','received','cancelled'],                               'pending');
SELECT pg_temp.enum_col_to_text('dispatches',      'status',        'chk_dispatches_status',
        ARRAY['draft','saved','dispatched','reconciled'],                      'draft');
SELECT pg_temp.enum_col_to_text('stock_movements', 'movement_type', 'chk_stock_movements_movement_type',
        ARRAY['po_receipt','dispatch','adjustment','cancellation_reversal'],   NULL);
SELECT pg_temp.enum_col_to_text('weekly_menus',    'status',        'chk_weekly_menus_status',
        ARRAY['draft','active','archived'],                                    'draft');
SELECT pg_temp.enum_col_to_text('restock_events',  'action',        'chk_restock_events_action',
        ARRAY['added','removed'],                                              NULL);
SELECT pg_temp.enum_col_to_text('restock_events',  'tag_status',    'chk_restock_events_tag_status',
        ARRAY['valid','unreliable','unrecognised'],                           'valid');
SELECT pg_temp.enum_col_to_text('dispatch_lines',  'source',        'chk_dispatch_lines_source',
        ARRAY['forecast','manual'],                                            'manual');
SELECT pg_temp.enum_col_to_text('alerts',          'alert_type',    'chk_alerts_alert_type',
        ARRAY['expiry','low_stock','below_target','negative_blocked','rfid_offline'], NULL);

-- ---------------------------------------------------------------------------
-- 4. Recreate the multi-column CHECKs with TEXT literals (NAMED to match ORM).
-- ---------------------------------------------------------------------------
SELECT pg_temp.add_check('dispatches', 'chk_dispatches_confirmed_stamp',
    $c$status NOT IN ('dispatched', 'reconciled') OR confirmed_at IS NOT NULL$c$);

SELECT pg_temp.add_check('stock_movements', 'chk_movement_sign',
    $c$(movement_type = 'po_receipt'            AND qty > 0) OR
       (movement_type = 'dispatch'              AND qty < 0) OR
       (movement_type = 'cancellation_reversal' AND qty < 0) OR
       (movement_type = 'adjustment')$c$);

SELECT pg_temp.add_check('stock_movements', 'chk_adjustment_reason',
    $c$movement_type <> 'adjustment' OR (reason IS NOT NULL AND btrim(reason) <> '')$c$);

SELECT pg_temp.add_check('stock_movements', 'chk_movement_reference',
    $c$(movement_type IN ('po_receipt', 'cancellation_reversal') AND po_line_id IS NOT NULL) OR
       (movement_type = 'dispatch'                               AND dispatch_line_id IS NOT NULL) OR
       (movement_type = 'adjustment')$c$);

-- ---------------------------------------------------------------------------
-- 5. Recreate v_stock_balances (identical to schema.sql SECTION 10).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_stock_balances AS
WITH physical AS (
    SELECT sm.product_id,
           SUM(sm.qty) AS physical_qty
      FROM stock_movements sm
     GROUP BY sm.product_id
),
on_order AS (
    SELECT pol.product_id,
           SUM(GREATEST(pol.qty_ordered - pol.qty_received, 0)) AS on_order_qty
      FROM purchase_order_lines pol
      JOIN purchase_orders po ON po.id = pol.po_id
     WHERE po.status = 'pending'
     GROUP BY pol.product_id
)
SELECT p.id                                                          AS product_id,
       p.code                                                        AS product_code,
       p.name                                                        AS product_name,
       COALESCE(ph.physical_qty, 0)::BIGINT                          AS physical_qty,
       COALESCE(oo.on_order_qty, 0)::BIGINT                          AS on_order_qty,
       (COALESCE(oo.on_order_qty, 0) + COALESCE(ph.physical_qty, 0))::BIGINT AS available_qty
  FROM products p
  LEFT JOIN physical ph ON ph.product_id = p.id
  LEFT JOIN on_order oo ON oo.product_id = p.id;

-- ---------------------------------------------------------------------------
-- 6. Additional NAMED CHECK from the datatype/CHECK review.
--    Husky ratings are a thumbs model (1 positive, -1/0 negative). Live data is
--    {-1, 1}; the ops test seeds 0 as a negative. Bound to that domain.
-- ---------------------------------------------------------------------------
SELECT pg_temp.add_check('product_reviews', 'chk_product_reviews_rating',
    $c$rating IN (-1, 0, 1)$c$);

-- ---------------------------------------------------------------------------
-- 7. Drop the now-orphaned enum TYPES (every dependent column is text now).
-- ---------------------------------------------------------------------------
DROP TYPE IF EXISTS user_role;
DROP TYPE IF EXISTS po_status;
DROP TYPE IF EXISTS dispatch_status;
DROP TYPE IF EXISTS stock_movement_type;
DROP TYPE IF EXISTS menu_status;
DROP TYPE IF EXISTS restock_action;
DROP TYPE IF EXISTS tag_status;
DROP TYPE IF EXISTS line_source;
DROP TYPE IF EXISTS alert_type;

COMMIT;

-- ============================================================================
-- END OF MIGRATION 0003
-- ============================================================================
