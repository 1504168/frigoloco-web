-- ============================================================================
-- Migration 0002 — Money columns: NUMERIC(10,2) euros -> BIGINT minor units (cents)
-- ============================================================================
-- Decision (2026-07-03, user): store every monetary column as int64 minor units
-- (cents), matching the Husky API's int64 contract. Euros exist only at the API
-- presentation edge; the JSON contract (a 2-decimal euro string) is unchanged.
--
-- Columns are NOT renamed — purchase_price/sales_price/etc keep their names; the
-- semantic change (euros -> cents) is documented in schema.sql and CLAUDE.md.
--
-- Idempotent: each column is converted through a temp helper that checks
-- information_schema for the column's CURRENT data_type and only alters when it
-- is still 'numeric'. Re-running the file after a successful apply is a no-op.
--
-- Value columns converted with round(c * 100); vat_rate / pos_fee_pct_snapshot /
-- forecast_qty / *_score columns are fractions or quantities and stay NUMERIC.
-- ============================================================================

BEGIN;

-- Guarded, DRY converter: skips a column whose type is no longer numeric.
CREATE OR REPLACE FUNCTION pg_temp.money_col_to_cents(
    p_table    text,
    p_col      text,
    p_default  text   -- new bigint DEFAULT to restore, or NULL for no default
) RETURNS void
LANGUAGE plpgsql
AS $fn$
DECLARE
    cur_type text;
BEGIN
    SELECT data_type INTO cur_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name   = p_table
       AND column_name  = p_col;

    IF cur_type IS NULL THEN
        RAISE NOTICE 'migration 0002: %.% not found — skipped', p_table, p_col;
        RETURN;
    END IF;

    IF cur_type <> 'numeric' THEN
        RAISE NOTICE 'migration 0002: %.% already %, skipped', p_table, p_col, cur_type;
        RETURN;
    END IF;

    -- Drop any existing DEFAULT (euros) so the type change never tries to cast it.
    EXECUTE format('ALTER TABLE %I ALTER COLUMN %I DROP DEFAULT', p_table, p_col);
    EXECUTE format(
        'ALTER TABLE %I ALTER COLUMN %I TYPE bigint USING round(%I * 100)::bigint',
        p_table, p_col, p_col
    );
    IF p_default IS NOT NULL THEN
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I SET DEFAULT %s',
                       p_table, p_col, p_default);
    END IF;
    RAISE NOTICE 'migration 0002: converted %.% -> bigint cents', p_table, p_col;
END;
$fn$;

-- --- Master data -----------------------------------------------------------
SELECT pg_temp.money_col_to_cents('products',                'purchase_price', '0');
SELECT pg_temp.money_col_to_cents('products',                'sales_price',    '0');
SELECT pg_temp.money_col_to_cents('fridge_product_prices',   'sales_price',    NULL);
SELECT pg_temp.money_col_to_cents('client_fees',             'yearly_fee',     NULL);
SELECT pg_temp.money_col_to_cents('client_service_charges',  'amount',         NULL);

-- --- Purchase orders -------------------------------------------------------
SELECT pg_temp.money_col_to_cents('purchase_orders',         'total_ex_vat',   '0');
SELECT pg_temp.money_col_to_cents('purchase_orders',         'total_vat',      '0');
SELECT pg_temp.money_col_to_cents('purchase_orders',         'total_incl_vat', '0');
SELECT pg_temp.money_col_to_cents('purchase_order_lines',    'unit_price',     NULL);

-- --- Dispatch price snapshots (nullable, no default) -----------------------
SELECT pg_temp.money_col_to_cents('dispatch_lines',          'unit_purchase_price', NULL);
SELECT pg_temp.money_col_to_cents('dispatch_lines',          'unit_sales_price',    NULL);

-- --- Raw RFID sales events -------------------------------------------------
SELECT pg_temp.money_col_to_cents('sales_events',            'unit_price',      NULL);
SELECT pg_temp.money_col_to_cents('sales_events',            'discount_amount', '0');

-- --- Reconciliation --------------------------------------------------------
SELECT pg_temp.money_col_to_cents('restock_verification_lines', 'diff_value',  '0');

-- --- Weekly financials (manual money inputs + RFID fee snapshot) -----------
SELECT pg_temp.money_col_to_cents('weekly_financials',       'catering_turnover',  '0');
SELECT pg_temp.money_col_to_cents('weekly_financials',       'catering_food_cost', '0');
SELECT pg_temp.money_col_to_cents('weekly_financials',       'tgtg_turnover',      '0');
SELECT pg_temp.money_col_to_cents('weekly_financials',       'logistics_cost',     '0');
-- rfid_fee_snapshot was EUR 0.10 -> 10 cents; restore the cents default.
SELECT pg_temp.money_col_to_cents('weekly_financials',       'rfid_fee_snapshot',  '10');

-- --- Settings: the RFID fee value is now expressed in cents ----------------
-- pos_fee_pct stays a fraction (0.09). rfid_fee_eur 0.10 euros -> 10 cents.
UPDATE settings
   SET value = '10'::jsonb
 WHERE key = 'rfid_fee_eur'
   AND value::text IN ('0.1', '0.10');

COMMIT;

-- ============================================================================
-- END OF MIGRATION 0002
-- ============================================================================
