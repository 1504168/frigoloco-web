-- ============================================================================
-- Migration 0021 - purchase_order_receipts (one row per "Receive goods" action)
-- ============================================================================
-- Receiving goods can happen in several partial deliveries, and the warehouse
-- needs to log issues per delivery ("2 boxes broken", "arrived a day late").
-- A comment on purchase_orders would hold one note for the whole order, so each
-- receive action becomes its own receipt row carrying the comment, the user and
-- the time. The po_receipt stock movements it created point back at it through
-- stock_movements.receipt_id, so the PO detail can show units per receipt.
-- Receipts made before this migration have no receipt row (receipt_id NULL).
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS purchase_order_receipts (
    id          INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_id       INTEGER      NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    comment     TEXT,
    created_by  INTEGER      REFERENCES users(id),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_purchase_order_receipts_po
    ON purchase_order_receipts (po_id, created_at);

ALTER TABLE stock_movements
    ADD COLUMN IF NOT EXISTS receipt_id INTEGER REFERENCES purchase_order_receipts(id);

CREATE INDEX IF NOT EXISTS ix_stock_movements_receipt
    ON stock_movements (receipt_id)
    WHERE receipt_id IS NOT NULL;

COMMENT ON TABLE purchase_order_receipts IS
    'One row per Receive goods action on a purchase order, with the free-text receipt comment (issues such as broken or delayed goods).';

COMMIT;
