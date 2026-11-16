import type { PoDiscrepancyReason, PoHistoryAction, PurchaseOrderLine } from '../types'

export const DISCREPANCY_REASON_LABELS: Record<PoDiscrepancyReason, string> = {
  missing: 'Missing',
  damaged: 'Damaged',
  wrong_product: 'Wrong product',
  other: 'Other',
}

export const DISCREPANCY_REASONS = Object.keys(DISCREPANCY_REASON_LABELS) as PoDiscrepancyReason[]

export const HISTORY_ACTION_LABELS: Record<PoHistoryAction, string> = {
  created: 'Created',
  edited: 'Edited',
  received: 'Goods received',
  closed_short: 'Closed with received quantities',
  cancelled: 'Cancelled',
}

export const CLOSE_SHORT_LABEL = 'Close with received quantities'

export function shortfallOf(line: PurchaseOrderLine): number {
  return Math.max(line.qty_ordered - line.qty_received, 0)
}
