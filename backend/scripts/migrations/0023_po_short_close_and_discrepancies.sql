-- ============================================================================
-- Migration 0023 - PO short-close status + purchase_order_discrepancies
-- ============================================================================
-- Why: a supplier often delivers fewer units than ordered (or more). Until now
-- a short delivery left the PO "pending" forever, its open remainder kept
-- counting as on order, and the difference was logged nowhere.
--
-- 1. purchase_orders.status gains 'closed_short': "Close with received
--    quantities". v_stock_balances counts the open remainder of PENDING orders
--    only, so a closed_short order drops out of on_order_qty with no view change.
-- 2. purchase_order_discrepancies: one row per line whose received units differ
--    from the ordered units. kind 'short' rows are written when the PO is closed
--    short (with an optional reason and comment); kind 'over' rows are written
--    when an acknowledged over-receipt is booked (receipt_id points at it).
--    qty_difference is always positive: the shortfall or the excess.
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

ALTER TABLE purchase_orders DROP CONSTRAINT IF EXISTS chk_purchase_orders_status;
ALTER TABLE purchase_orders
    ADD CONSTRAINT chk_purchase_orders_status
    CHECK (status IN ('pending', 'received', 'closed_short', 'cancelled'));

CREATE TABLE IF NOT EXISTS purchase_order_discrepancies (
    id              INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_id           INTEGER      NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    po_line_id      INTEGER      NOT NULL REFERENCES purchase_order_lines(id) ON DELETE CASCADE,
    receipt_id      INTEGER      REFERENCES purchase_order_receipts(id) ON DELETE CASCADE,
    kind            TEXT         NOT NULL
                                 CONSTRAINT chk_po_discrepancies_kind
                                 CHECK (kind IN ('short', 'over')),
    qty_ordered     INTEGER      NOT NULL,
    qty_received    INTEGER      NOT NULL,
    qty_difference  INTEGER      NOT NULL
                                 CONSTRAINT chk_po_discrepancies_difference_positive
                                 CHECK (qty_difference > 0),
    reason          TEXT
                                 CONSTRAINT chk_po_discrepancies_reason
                                 CHECK (reason IS NULL OR reason IN ('missing', 'damaged', 'wrong_product', 'other')),
    comment         TEXT,
    created_by      INTEGER      REFERENCES users(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_purchase_order_discrepancies_po
    ON purchase_order_discrepancies (po_id);
CREATE INDEX IF NOT EXISTS ix_purchase_order_discrepancies_created
    ON purchase_order_discrepancies (created_at);

COMMENT ON TABLE purchase_order_discrepancies IS
    'One row per PO line whose received units differ from the ordered units: kind short (written when the PO is closed with received quantities, optional reason + comment) or over (written when an acknowledged over-receipt is booked). qty_difference is the positive shortfall or excess.';

COMMIT;
