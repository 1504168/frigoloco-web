/** Response types for GET /api/v1/reports/restock and /api/v1/reports/loss. */

export interface RestockReportRow {
  delivery_date: string
  fridge_id: number
  fridge_name: string
  product_id: number
  product_code: string
  product_name: string
  category: string
  dispatched_qty: number
  added_qty: number
  /** added_qty - dispatched_qty: negative means units dispatched but never scanned in. */
  gap_qty: number
}

export interface RestockReport {
  date_from: string
  date_to: string
  rows: RestockReportRow[]
  total_dispatched_qty: number
  total_added_qty: number
  total_gap_qty: number
}

export interface LossReportRow {
  iso_year: number
  iso_week: number
  week_start: string
  fridge_id: number
  fridge_name: string
  product_id: number
  product_code: string
  product_name: string
  category: string
  removed_qty: number
  unit_purchase_price: string
  loss_cost: string
}

export interface LossReport {
  date_from: string
  date_to: string
  rows: LossReportRow[]
  total_removed_qty: number
  total_loss_cost: string
}

/** Date range plus optional filters, as sent to the report endpoints. */
export interface ReportScope {
  from: string
  to: string
  fridgeId: number | null
  categoryId: number | null
}
