/**
 * Backend entity types for the OPS pipeline (Forecast → Menu → Dispatch).
 * Mirrored verbatim from the live FastAPI OpenAPI schema at
 * http://localhost:8100/openapi.json and the wave-2 API contract. Everything
 * keys on the (iso_year, week_no, day_name) pipeline triple.
 */

// ── Forecast ───────────────────────────────────────────────────────────────

/** POST /api/v1/forecasts/run body (schema: ForecastRunRequest). */
export interface ForecastRunRequest {
  delivery_date: string
  fridge_ids?: number[] | null
  model?: string
  params?: Record<string, unknown> | null
}

/** POST /api/v1/forecasts/save body (schema: ForecastSaveRequest). */
export interface ForecastSaveRequest {
  year: number
  week: number
  day_name: string
  fridge_ids?: number[] | null
  model?: string
  params?: Record<string, unknown> | null
  overwrite?: boolean
}

/** One fridge×category forecast cell (schema: ForecastResultOut). */
export interface ForecastResult {
  fridge_id: number
  category_id: number
  /** Decimal string, e.g. "12.50". */
  forecast_qty: string
  valid_days: number
  holiday_days: number
}

/** Per-fridge config echoed inside a run's params.fridge_config. */
export interface FridgeConfig {
  min_daily_qty: number
  days_to_fill: number
}

/** One fridge×category actuals cell (schema: ForecastActualCell). */
export interface ForecastActualCell {
  fridge_id: number
  category_id: number
  added_qty: number
  sold_qty: number
  /** sold/added as a decimal string, e.g. "0.8571"; null when nothing was added. */
  ratio: string | null
}

/** GET /api/v1/forecasts/actuals response (schema: ForecastActualsOut). */
export interface ForecastActuals {
  year: number
  week: number
  day_name: string
  delivery_date: string
  window_start: string
  window_end: string
  cells: ForecastActualCell[]
}

/** POST /run · /save · GET /saved response (schema: ForecastRunOut). */
export interface ForecastRun {
  run_id: number
  delivery_date: string
  iso_year: number
  week_no: number
  day_name: string
  run_at: string
  model: string
  is_saved: boolean
  params: {
    fridge_config?: Record<string, FridgeConfig>
    [key: string]: unknown
  }
  results: ForecastResult[]
}

// ── Shared grid shape (MenuGridOut and DispatchMatrix are structurally equal) ─

export interface GridFridge {
  fridge_id: number
  friendly_name: string
}

export interface GridProduct {
  product_id: number
  product_name: string
  category_id: number
}

export interface GridCategory {
  category_id: number
  category_name: string
  product_ids: number[]
}

export interface GridCell {
  fridge_id: number
  product_id: number
  qty: number
}

/** GET/POST menus/* response (schema: MenuGridOut). menu_id is null on preview. */
export interface MenuGrid {
  menu_id: number | null
  year: number
  week: number
  day_name: string
  fridges: GridFridge[]
  products: GridProduct[]
  categories: GridCategory[]
  cells: GridCell[]
}

/** One line in a menu/dispatch save body (schema: MenuLineItem / DispatchLineItem). */
export interface GridLineItem {
  fridge_id: number
  product_id: number
  qty: number
  source?: 'forecast' | 'manual'
}

/** POST /api/v1/menus/save body (schema: MenuSaveRequest). */
export interface MenuSaveRequest {
  year: number
  week: number
  day_name: string
  lines: GridLineItem[]
  overwrite?: boolean
}

// ── Dispatch ────────────────────────────────────────────────────────────---

export type DispatchStatus = 'draft' | 'saved' | 'dispatched' | 'reconciled'

/** GET /api/v1/dispatches/saved response (schema: DispatchRead) — metadata only. */
export interface DispatchRead {
  id: number
  delivery_date: string
  iso_week: number
  weekday: number
  status: DispatchStatus
  confirmed_by: number | null
  confirmed_at: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

/** POST import-from-menu · GET /{id}/matrix response (schema: DispatchMatrix). */
export interface DispatchMatrix {
  dispatch_id: number
  fridges: GridFridge[]
  products: GridProduct[]
  categories: GridCategory[]
  cells: GridCell[]
}

/** POST /api/v1/dispatches/save body (schema: DispatchSaveRequest). */
export interface DispatchSaveRequest {
  year: number
  week: number
  day_name: string
  lines: GridLineItem[]
  overwrite?: boolean
}

/** POST /api/v1/dispatches/create-individual response (schema: ConfirmResult). */
export interface ConfirmResult {
  dispatch_id: number
  status: DispatchStatus
  movements_created: number
}

/** Shape of the 409 `stock_blocked` error `details` array. */
export interface StockBlockedEntry {
  product_id: number
  requested: number
  available: number
}

// ── Reference / catalogue ──────────────────────────────────────────────────

/** GET /api/v1/fridges item (subset used by ops pages). */
export interface Fridge {
  id: number
  friendly_name: string
  husky_name: string
  is_active: boolean
}

/** GET /api/v1/categories item (bare array, not a Page<T>). */
export interface Category {
  id: number
  name: string
  display_order: number
  dispatch_print_order: number
}

/** GET /api/v1/suppliers item (subset). */
export interface Supplier {
  id: number
  name: string
  is_active: boolean
}

/** GET /api/v1/settings item (schema: SettingRead). */
export interface Setting {
  key: string
  value: unknown
  description: string | null
  updated_at: string
}

/** GET /api/v1/rating/scorecard item (subset used for the Menu score row). */
export interface ScorecardItem {
  product_id: number
  final_score: string
}

/** GET /api/v1/purchase-orders draft response (schema: PurchaseOrderRead, subset). */
export interface PurchaseOrder {
  id: number
  order_no: string
  supplier_id: number
  status: string
  total_incl_vat: string
}
