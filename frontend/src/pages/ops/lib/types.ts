/**
 * Backend entity types for the OPS pipeline (Forecast → Menu → Dispatch).
 * Mirrored verbatim from the live FastAPI OpenAPI schema at
 * http://localhost:8100/openapi.json and the wave-2 API contract. Everything
 * keys on the (iso_year, week_no, day_name) pipeline triple. The reference
 * entities the pipeline reads (Fridge, Category, Supplier, Setting,
 * PurchaseOrder) are defined once in src/lib/types.ts and re-exported here.
 */

export type {
  Category,
  Fridge,
  PurchaseOrder,
  Setting,
  Supplier,
} from '@/lib/types'

// ── Forecast ───────────────────────────────────────────────────────────────

/** POST /api/v1/forecasts/run body (schema: ForecastRunRequest). */
export interface ForecastRunRequest {
  delivery_date: string
  fridge_ids?: number[] | null
  model?: string
  params?: Record<string, unknown> | null
}

/** One on-screen forecast quantity sent on save (schema: ForecastCellEdit). */
export interface ForecastCellEdit {
  fridge_id: number
  category_id: number
  forecast_qty: number
}

/** POST /api/v1/forecasts/save body (schema: ForecastSaveRequest). */
export interface ForecastSaveRequest {
  run_id: number
  cells: ForecastCellEdit[]
  overwrite?: boolean
}

/** GET /api/v1/forecasts/models item (schema: ForecastModelOut). */
export interface ForecastModel {
  code: string
  label: string
}

/** One fridge×category forecast cell (schema: ForecastResultOut). */
export interface ForecastResult {
  fridge_id: number
  category_id: number
  /** Net decimal string, e.g. "12.50": gross_qty minus residual_units, never below 0. */
  forecast_qty: string
  /** Before the in-fridge stock deduction; null on runs older than migration 0024. */
  gross_qty: string | null
  /** Good in-fridge stock units deducted; null on runs older than migration 0024. */
  residual_units: number | null
  valid_days: number
  holiday_days: number
}

/** Per-fridge config echoed inside a run's params.fridge_config. */
export interface FridgeConfig {
  min_daily_qty: number
  /** Calendar days until the next delivery. */
  days_to_fill: number
  /** Selling days the delivery covers (weekends and bank holidays left out); absent on old runs. */
  selling_days_to_fill?: number
  active_on_weekends?: boolean
}

/** Units one fridge sold in the run's sales window (schema: FridgeWindowSalesOut). */
export interface FridgeWindowSales {
  fridge_id: number
  sold_units: number
}

/** GET /api/v1/forecasts/saved-list item (schema: SavedForecastOut). */
export interface SavedForecast {
  run_id: number
  delivery_date: string
  iso_year: number
  week_no: number
  day_name: string
  model: string
  run_at: string
}

/** GET/POST /api/v1/forecasts/bank-holidays item (schema: BankHolidayOut). */
export interface BankHoliday {
  holiday_date: string
  label: string
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
  /** Exclusive. */
  window_end: string
  /** ISO weekdays (1-7) the window was narrowed to; null = every day. */
  weekdays: number[] | null
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
    excluded_bank_holidays?: string[]
    [key: string]: unknown
  }
  results: ForecastResult[]
  window_start: string
  /** Exclusive: the day after the last sales day in the window. */
  window_end: string
  window_sales_units: number
  window_sales_by_fridge: FridgeWindowSales[]
  hidden_category_ids: number[]
  residual_applied: boolean
  /** Holiday label when the delivery date is a bank holiday. */
  delivery_bank_holiday: string | null
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

/** POST /api/v1/menus/import-from-forecast body (schema: MenuImportRequest). */
export interface MenuImportRequest {
  /** The products on screen; omit to use the saved week menu. */
  product_ids?: number[]
  sold_first: boolean
  /** Give each product only what it needs beyond its good units in the fridge. */
  use_fridge_stock: boolean
  /** Scale a fridge x category up or down by how fast it sells against its last forecast. */
  sales_speed: boolean
  /** Cut each product to the physical warehouse stock, proportionally per fridge. */
  fit_to_stock?: boolean
}

/** A product the fridges asked more of than the warehouse holds (schema: WarehouseStockCutOut). */
export interface WarehouseStockCut {
  product_id: number
  requested: number
  in_stock: number
  cut: number
}

/** Good units a product already has in a fridge and how much they cut its import. */
export interface MenuStockCut {
  fridge_id: number
  product_id: number
  in_fridge_units: number
  reduced_by: number
}

/** Whose hourly sales shaped a sales-speed profile. */
export type SalesProfileSource = 'fridge' | 'category' | 'linear'

/** A fridge x category forecast scaled by its sales speed (decimals arrive as strings). */
export interface SalesSpeedAdjustment {
  fridge_id: number
  category_id: number
  /** The previous delivery's forecast for the time until the next delivery. */
  forecast_units: string
  sold_units: number
  /** Forecast units still expected until the next delivery. */
  remaining_units: string
  pace: string
  factor: string
  profile_source: SalesProfileSource
}

/** A product a sales-speed raise skipped because it would expire before the coverage end. */
export interface ShelfLifeHold {
  fridge_id: number
  product_id: number
  raised_qty: number
  kept_qty: number
  shelf_life_days: number
  coverage_days: number
}

/** POST /api/v1/menus/import-from-forecast response (schema: MenuImportOut). */
export interface MenuImport {
  grid: MenuGrid
  /** True when nothing was chosen for the imported scope, so products came from ratings. */
  used_rating_suggestion: boolean
  categories_without_products: number[]
  sold_first: boolean
  /** False when the switch was off or the delivery is not the next one. */
  fridge_stock_applied: boolean
  /** Fridges whose stock reading is missing or older than 2 hours. */
  stale_stock_fridge_ids: number[]
  stock_cuts: MenuStockCut[]
  sales_speed_adjustments: SalesSpeedAdjustment[]
  shelf_life_holds: ShelfLifeHold[]
  /** Products without a score that got units, split with their category's mean score. */
  default_score_product_ids: number[]
  warehouse_stock_cuts: WarehouseStockCut[]
  /** Fridges whose Snacks and Drinks were refilled to their targets. */
  target_refill_fridge_ids: number[]
  /** Imported cells whose client excludes one of the product's tags: a warning, never a block. */
  rule_violations: ClientRuleViolation[]
}

/** A product on a fridge whose client excludes one of its tags (schema: ClientRuleViolation). */
export interface ClientRuleViolation {
  fridge_id: number
  product_id: number
  rule_id: number
  tag: string
  note: string | null
}

/** GET /api/v1/menus/week: the products chosen for an ISO week (schema: WeekMenuOut). */
export interface WeekMenu {
  menu_id: number | null
  year: number
  week: number
  categories: GridCategory[]
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
  /** When set, only this category's lines are replaced; others stay intact. */
  category_id?: number | null
}

// ── Dispatch ────────────────────────────────────────────────────────────---

export type DispatchStatus = 'draft' | 'saved' | 'dispatched' | 'reconciled'

/** GET /api/v1/dispatches/saved response (schema: DispatchRead) - metadata only. */
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
  /** When set, only this category's lines are replaced; others stay intact. */
  category_id?: number | null
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

/** GET /api/v1/rating/scorecard item (subset used for the Menu score row). */
export interface ScorecardItem {
  product_id: number
  final_score: string
}
