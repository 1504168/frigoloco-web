-- ============================================================================
-- Migration 0004 - dispatch_lines -> monthly RANGE-partitioned table
-- ============================================================================
-- Decision (2026-07-03, user): dispatch_lines is the largest projected operational
-- table (the Excel GlobalDispatchHistoryTable was 20,692 rows and growing). Make
-- it RANGE-partitioned monthly, mirroring the sales_events / restock_events
-- pattern, so old months can be detached/archived and queries prune by date.
--
-- The partition key is delivery_date, DENORMALISED onto each line from the parent
-- dispatches row (a dispatch's delivery_date is immutable, so the copy can never
-- drift). PostgreSQL requires the partition key to be part of every unique key,
-- so:
--   * PRIMARY KEY becomes (id, delivery_date)
--   * the natural UNIQUE key gains delivery_date: (dispatch_id, fridge_id,
--     product_id, delivery_date)
--
-- A partitioned table cannot be the target of a foreign key on id alone (no
-- unique constraint on id by itself), so the incoming
-- stock_movements.dispatch_line_id FK is DROPPED. That link is now enforced by
-- the application; the id value is still stored for joins.
--
-- Near-empty today (a handful of rows), so the table is recreated and rows are
-- copied. Idempotent: if dispatch_lines is already partitioned, the whole body
-- is skipped.
--
-- partition_maintenance duty: create_next_month_event_partitions() (schema.sql)
-- is extended to also roll dispatch_lines partitions forward each month.
-- ============================================================================

BEGIN;

DO $mig$
DECLARE
    is_partitioned boolean;
    max_id         bigint;
    m              date;
    suffix         text;
BEGIN
    SELECT c.relkind = 'p'
      INTO is_partitioned
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'dispatch_lines';

    IF is_partitioned THEN
        RAISE NOTICE 'migration 0004: dispatch_lines already partitioned - skipped';
        RETURN;
    END IF;

    -- 1. Drop the incoming FK (can't reference a partitioned table by id alone).
    ALTER TABLE stock_movements
        DROP CONSTRAINT IF EXISTS stock_movements_dispatch_line_id_fkey;

    -- 2. Free the schema-global index names, then move the current table aside.
    ALTER INDEX dispatch_lines_pkey RENAME TO dispatch_lines_old_pkey;
    ALTER INDEX ix_dispatch_lines_fridge RENAME TO ix_dispatch_lines_old_fridge;
    ALTER INDEX ix_dispatch_lines_product RENAME TO ix_dispatch_lines_old_product;
    ALTER TABLE dispatch_lines RENAME TO dispatch_lines_old;

    -- 3. Create the partitioned parent (NAMED constraints, mirroring the ORM).
    CREATE TABLE dispatch_lines (
        id                   INTEGER        GENERATED ALWAYS AS IDENTITY,
        dispatch_id          INTEGER        NOT NULL REFERENCES dispatches(id) ON DELETE CASCADE,
        fridge_id            INTEGER        NOT NULL REFERENCES fridges(id),
        product_id           INTEGER        NOT NULL REFERENCES products(id),
        -- Denormalised partition key (== dispatches.delivery_date).
        delivery_date        DATE           NOT NULL,
        qty                  INTEGER        NOT NULL
                                            CONSTRAINT chk_dispatch_lines_qty_positive CHECK (qty > 0),
        source               TEXT           NOT NULL DEFAULT 'manual'
                                            CONSTRAINT chk_dispatch_lines_source CHECK (source IN ('forecast', 'manual')),
        unit_purchase_price  BIGINT,        -- cents
        unit_sales_price     BIGINT,        -- cents
        vat_rate             NUMERIC(6,4),
        CONSTRAINT dispatch_lines_pkey PRIMARY KEY (id, delivery_date),
        CONSTRAINT uq_dispatch_lines_dispatch_fridge_product
            UNIQUE (dispatch_id, fridge_id, product_id, delivery_date)
    ) PARTITION BY RANGE (delivery_date);

    -- 4. Pre-create monthly partitions 2025-01 .. 2027-12.
    m := DATE '2025-01-01';
    WHILE m <= DATE '2027-12-01' LOOP
        suffix := to_char(m, 'YYYY_MM');
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS dispatch_lines_%s PARTITION OF dispatch_lines
             FOR VALUES FROM (%L) TO (%L)',
            suffix, m, (m + INTERVAL '1 month')::date);
        m := (m + INTERVAL '1 month')::date;
    END LOOP;

    -- 5. Copy existing rows, denormalising delivery_date, preserving ids.
    INSERT INTO dispatch_lines (
        id, dispatch_id, fridge_id, product_id, delivery_date, qty, source,
        unit_purchase_price, unit_sales_price, vat_rate
    )
    OVERRIDING SYSTEM VALUE
    SELECT dl.id, dl.dispatch_id, dl.fridge_id, dl.product_id, d.delivery_date,
           dl.qty, dl.source, dl.unit_purchase_price, dl.unit_sales_price, dl.vat_rate
      FROM dispatch_lines_old dl
      JOIN dispatches d ON d.id = dl.dispatch_id;

    -- 6. Advance the identity past the copied ids.
    SELECT COALESCE(MAX(id), 0) INTO max_id FROM dispatch_lines;
    IF max_id > 0 THEN
        EXECUTE format('ALTER TABLE dispatch_lines ALTER COLUMN id RESTART WITH %s', max_id + 1);
    END IF;

    -- 7. Recreate the per-fridge / per-product access indexes.
    CREATE INDEX IF NOT EXISTS ix_dispatch_lines_fridge ON dispatch_lines (fridge_id);
    CREATE INDEX IF NOT EXISTS ix_dispatch_lines_product ON dispatch_lines (product_id);

    -- 8. Drop the old table.
    DROP TABLE dispatch_lines_old;

    RAISE NOTICE 'migration 0004: dispatch_lines converted to monthly RANGE partitions (2025-01..2027-12), % rows copied', max_id;
END;
$mig$;

-- Note: delivery_date is the partition key and MUST be supplied by the caller.
-- A trigger cannot backfill it - PostgreSQL rejects a NULL partition key during
-- tuple routing, before any BEFORE-INSERT trigger on the parent could run. The
-- dispatch service sets delivery_date = dispatch.delivery_date on every insert.

-- ---------------------------------------------------------------------------
-- Partition maintenance: dedicated helper + fold into the monthly scheduler hook
-- so dispatch_lines rolls forward alongside sales_events / restock_events.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION create_dispatch_line_partition_for_month(month_start DATE)
RETURNS VOID
LANGUAGE plpgsql
AS $$
-- Creates the monthly dispatch_lines partition covering month_start (idempotent).
DECLARE
    part_from DATE := date_trunc('month', month_start)::DATE;
    part_to   DATE := (date_trunc('month', month_start) + INTERVAL '1 month')::DATE;
    suffix    TEXT := to_char(part_from, 'YYYY_MM');
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS dispatch_lines_%s PARTITION OF dispatch_lines
         FOR VALUES FROM (%L) TO (%L)',
        suffix, part_from, part_to);
END;
$$;

CREATE OR REPLACE FUNCTION create_next_month_event_partitions()
RETURNS VOID
LANGUAGE plpgsql
AS $$
-- Scheduler hook: call monthly so the current AND next month's partitions always
-- exist ahead of inserts - for sales_events, restock_events AND dispatch_lines.
DECLARE
    next_month DATE := (date_trunc('month', CURRENT_DATE) + INTERVAL '1 month')::DATE;
BEGIN
    PERFORM create_event_partitions_for_month(CURRENT_DATE);
    PERFORM create_event_partitions_for_month(next_month);
    PERFORM create_dispatch_line_partition_for_month(CURRENT_DATE);
    PERFORM create_dispatch_line_partition_for_month(next_month);
END;
$$;

COMMIT;

-- ============================================================================
-- END OF MIGRATION 0004
-- ============================================================================
