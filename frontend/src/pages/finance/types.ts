/**
 * Finance / Verification / Settings types, mirrored from the FastAPI OpenAPI
 * schema (verified live against http://localhost:8000/openapi.json). The
 * cross-domain entities this page reads (Fridge, Category, Setting) are defined
 * once in src/lib/types.ts and re-exported here.
 *
 * MONEY CONTRACT: every money field arrives as a decimal-euro string (e.g.
 * "16904.00"). A concurrent backend migration is moving internal storage to
 * cents, but the API contract (euro strings) is guaranteed stable: this code
 * only ever reads/writes euro strings.
 */

export type { Category, Fridge, Setting } from '@/lib/types'

/** Manual weekly entries echoed back on GET (schema: WeeklyInputsRead). */
export interface WeeklyInputs {
  catering_turnover: string
  catering_food_cost: string
  tgtg_turnover: string
  logistics_cost: string
  drops_count: number
  unsold_items: number
  fridge_count: number | null
  remarks: string | null
}

/** Editable manual inputs sent on PUT (schema: WeeklyFinancialInputs). */
export interface WeeklyFinancialInputs {
  catering_turnover: string
  catering_food_cost: string
  tgtg_turnover: string
  logistics_cost: string
  drops_count: number
  unsold_items: number
  fridge_count: number | null
  remarks: string | null
}

/** GET/PUT /api/v1/finance/weekly/{year}/{week} (schema: WeeklyPnlRead). */
export interface WeeklyPnl {
  year: number
  iso_week: number
  week_start: string
  inputs: WeeklyInputs
  gross_sales: string
  refunds: string
  customer_credit: string
  frigoloco_discounts: string
  items_sold: number
  turnover_ex_vat: string
  fridge_food_cost_added: string
  pos_fee_pct: string
  rfid_fee_rate: string
  pos_fee: string
  rfid_fee: string
  net_margin: string
}

/** Monthly P&L dimension. */
export type MonthlyDimension = 'client' | 'supplier' | 'category'

/**
 * One P&L row (schema: MonthlyAnalysisRow). Which optional columns are
 * populated depends on the dimension:
 *   - client:   sales, pos_fee, fee_share, service_additionals, logistics_share
 *   - supplier: rfid_fee (sales/pos_fee are null)
 *   - category: rfid_fee (sales/pos_fee are null)
 */
export interface MonthlyAnalysisRow {
  key_id: number | null
  key_name: string
  food_margin: string
  rfid_fee: string | null
  sales: string | null
  pos_fee: string | null
  fee_share: string | null
  service_additionals: string | null
  logistics_share: string | null
  net_margin: string
}

/** GET /api/v1/finance/monthly (schema: MonthlyAnalysisRead). */
export interface MonthlyAnalysis {
  month: string
  dimension: string
  rows: MonthlyAnalysisRow[]
}

/** One per-product row of the fridge report (schema: FridgeReportRow). */
export interface FridgeReportRow {
  product_id: number
  code: string
  name: string
  /** Null for a product with no category. */
  category: string | null
  added_qty: number
  unit_buying_price: string
  unit_selling_price: string
}

/** GET /api/v1/finance/fridge-report (schema: FridgeReportRead). */
export interface FridgeReport {
  fridge_id: number
  date_from: string
  date_to: string
  added_qty: number
  food_cost: string
  revenue: string
  margin: string
  /** Food margin as a 0..1 fraction string, e.g. "0.6000". Null when there is no ex-VAT revenue to divide by. */
  margin_pct: string | null
  rows: FridgeReportRow[]
}

/** GET /api/v1/verifications item (schema: VerificationSummary). */
export interface VerificationSummary {
  id: number
  dispatch_id: number
  run_at: string
}

/** One reconciliation line (schema: VerificationLineRead). */
export interface VerificationLine {
  id: number
  fridge_id: number
  product_id: number
  dispatched_qty: number
  added_qty: number
  unreliable_qty: number
  diff_qty: number
  diff_value: string
}

/** Per-category reconciliation totals (schema: CategoryReconTotal). */
export interface CategoryReconTotal {
  category_id: number
  dispatched_qty: number
  added_qty: number
  unreliable_qty: number
  diff_qty: number
  diff_value: string
}

/** GET /api/v1/verifications/{id} (schema: VerificationRead). */
export interface VerificationDetail {
  id: number
  dispatch_id: number
  run_at: string
  lines: VerificationLine[]
  category_totals: CategoryReconTotal[]
}

/** Dispatch summary (schema: DispatchRead) — used by the verify picker. */
export interface Dispatch {
  id: number
  delivery_date: string
  iso_week: number
  weekday: number
  status: string
}
