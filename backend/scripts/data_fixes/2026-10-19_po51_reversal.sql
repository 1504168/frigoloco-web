-- One-off repair (TESTING DB only): PO 51 (2026-00001) was cancelled while partly
-- received (4 of 10 units of product 397), and the old cancel rule reversed stock
-- only for fully received orders, so the 4 received units stayed in stock.
-- A verifier later removed them with a manual adjustment (movement 259, -4), which
-- left the PO's own movements at net +4.
-- This script moves that correction onto the PO: it undoes adjustment 259 with a
-- +4 adjustment, then inserts the missing cancellation_reversal (-4). Product 397's
-- balance is unchanged and the PO's net movement becomes 0.
-- Safe to re-run: both inserts are skipped once the reversal exists.

BEGIN;

INSERT INTO stock_movements (product_id, qty, movement_type, reason, created_by)
SELECT
    adjustment.product_id,
    -adjustment.qty,
    'adjustment',
    'Data fix 2026-10-19: undo movement 259, replaced by the PO 51 cancellation reversal',
    NULL
FROM stock_movements AS adjustment
WHERE adjustment.id = 259
  AND adjustment.movement_type = 'adjustment'
  AND NOT EXISTS (
      SELECT 1
      FROM stock_movements AS movement
      JOIN purchase_order_lines AS line ON line.id = movement.po_line_id
      WHERE line.po_id = 51
        AND movement.movement_type = 'cancellation_reversal'
  );

INSERT INTO stock_movements (product_id, qty, movement_type, po_line_id, reason, created_by)
SELECT
    line.product_id,
    -line.qty_received,
    'cancellation_reversal',
    line.id,
    'Data fix 2026-10-19: reversal missed when partly received PO 51 was cancelled',
    NULL
FROM purchase_order_lines AS line
JOIN purchase_orders AS po ON po.id = line.po_id
WHERE po.id = 51
  AND po.status = 'cancelled'
  AND line.qty_received > 0
  AND NOT EXISTS (
      SELECT 1
      FROM stock_movements AS movement
      WHERE movement.po_line_id = line.id
        AND movement.movement_type = 'cancellation_reversal'
  );

SELECT COALESCE(SUM(movement.qty), 0) AS net_po_51_movement
FROM stock_movements AS movement
JOIN purchase_order_lines AS line ON line.id = movement.po_line_id
WHERE line.po_id = 51;

COMMIT;
