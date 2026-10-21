-- Testing DB only. Clears test rows that collide with real Excel history (order numbers, delivery dates).
-- Safe to re-run: every statement matches nothing once applied.
BEGIN;
-- Test POs with stock movements cannot be deleted (append-only ledger, FK on po_line_id):
-- renumber into year 9999, which passes the order_no CHECK and next_order_no() never reaches.
UPDATE purchase_orders SET order_no = '9999-' || right(order_no, 5), updated_at = now()
WHERE order_no IN ('2026-00001', '2026-00004', '2026-00008') AND created_by IS NULL;
DELETE FROM purchase_orders p
WHERE p.order_no IN ('2026-00002', '2026-00003', '2026-00005') AND p.created_by IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM stock_movements m JOIN purchase_order_lines l ON l.id = m.po_line_id WHERE l.po_id = p.id
  );
DELETE FROM dispatches d
WHERE d.id = 41 AND d.delivery_date = DATE '2026-07-10' AND d.created_by IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM stock_movements m JOIN dispatch_lines l ON l.id = m.dispatch_line_id WHERE l.dispatch_id = d.id
  );
COMMIT;
