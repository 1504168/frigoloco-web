/**
 * Explanations for the quantities a forecast import changed: the fridge-stock cut
 * per product (spec 0009), the sales-speed change per fridge x category and its
 * shelf-life holds (spec 0010), plus the warehouse "fit to stock" cuts and the
 * products split with a default score. They become grid cell tooltips and the
 * lines of compact notices.
 */
import { cellKey } from '@/pages/ops/lib/grid'
import type {
  ClientRuleViolation,
  GridCategory,
  MenuImport,
  MenuStockCut,
  SalesProfileSource,
  SalesSpeedAdjustment,
  ShelfLifeHold,
  WarehouseStockCut,
} from '@/pages/ops/lib/types'

const PERCENT = 100
const PROFILE_SOURCE_LABELS: Record<SalesProfileSource, string> = {
  fridge: "this fridge's hourly sales",
  category: "the category's hourly sales in all fridges",
  linear: 'an even spread (too little sales history)',
}

export interface ImportAdjustments {
  stockCuts: MenuStockCut[]
  speedAdjustments: SalesSpeedAdjustment[]
  shelfLifeHolds: ShelfLifeHold[]
  staleStockFridgeIds: number[]
  warehouseStockCuts: WarehouseStockCut[]
  /** Products without a score: split with their category's mean score. */
  defaultScoreProductIds: number[]
  ruleViolations: ClientRuleViolation[]
}

export const NO_IMPORT_ADJUSTMENTS: ImportAdjustments = {
  stockCuts: [],
  speedAdjustments: [],
  shelfLifeHolds: [],
  staleStockFridgeIds: [],
  warehouseStockCuts: [],
  defaultScoreProductIds: [],
  ruleViolations: [],
}

export function adjustmentsOfImport(result: MenuImport): ImportAdjustments {
  return {
    stockCuts: result.stock_cuts,
    speedAdjustments: result.sales_speed_adjustments,
    shelfLifeHolds: result.shelf_life_holds,
    staleStockFridgeIds: result.stale_stock_fridge_ids,
    warehouseStockCuts: result.warehouse_stock_cuts,
    defaultScoreProductIds: result.default_score_product_ids,
    ruleViolations: result.rule_violations,
  }
}

/** A category-scoped import replaces only that category's explanations. */
export function mergeCategoryAdjustments(
  previous: ImportAdjustments,
  result: MenuImport,
  scopeCategoryId: number,
  scopedProductIds: Set<number>,
): ImportAdjustments {
  const otherStockCuts = previous.stockCuts.filter(
    (stockCut) => !scopedProductIds.has(stockCut.product_id),
  )
  const otherSpeedAdjustments = previous.speedAdjustments.filter(
    (adjustment) => adjustment.category_id !== scopeCategoryId,
  )
  const otherShelfLifeHolds = previous.shelfLifeHolds.filter(
    (hold) => !scopedProductIds.has(hold.product_id),
  )
  const otherWarehouseStockCuts = previous.warehouseStockCuts.filter(
    (stockCut) => !scopedProductIds.has(stockCut.product_id),
  )
  const otherDefaultScoreProductIds = previous.defaultScoreProductIds.filter(
    (productId) => !scopedProductIds.has(productId),
  )
  const otherRuleViolations = previous.ruleViolations.filter(
    (violation) => !scopedProductIds.has(violation.product_id),
  )
  return {
    stockCuts: [...otherStockCuts, ...result.stock_cuts],
    speedAdjustments: [...otherSpeedAdjustments, ...result.sales_speed_adjustments],
    shelfLifeHolds: [...otherShelfLifeHolds, ...result.shelf_life_holds],
    // Stock is read fresh on every import, so the newest staleness replaces the old.
    staleStockFridgeIds: result.stale_stock_fridge_ids,
    warehouseStockCuts: [...otherWarehouseStockCuts, ...result.warehouse_stock_cuts],
    defaultScoreProductIds: [
      ...otherDefaultScoreProductIds,
      ...result.default_score_product_ids,
    ],
    ruleViolations: [...otherRuleViolations, ...result.rule_violations],
  }
}

/** Tooltip text per grid cell key (fridge:product), one line per explanation. */
export function buildCellHints(
  adjustments: ImportAdjustments,
  categories: GridCategory[],
  categoryName: (categoryId: number) => string,
): Map<string, string> {
  const hintLines = new Map<string, string[]>()
  const addHintLine = (key: string, line: string) => {
    hintLines.set(key, [...(hintLines.get(key) ?? []), line])
  }

  for (const stockCut of adjustments.stockCuts) {
    addHintLine(
      cellKey(stockCut.fridge_id, stockCut.product_id),
      `In fridge: ${stockCut.in_fridge_units} - reduced by ${stockCut.reduced_by}`,
    )
  }

  const productIdsByCategory = new Map(
    categories.map((category) => [category.category_id, category.product_ids]),
  )
  for (const adjustment of adjustments.speedAdjustments) {
    const speedText = describeSpeedAdjustment(adjustment, categoryName(adjustment.category_id))
    const categoryProductIds = productIdsByCategory.get(adjustment.category_id) ?? []
    for (const productId of categoryProductIds) {
      addHintLine(cellKey(adjustment.fridge_id, productId), speedText)
    }
  }

  for (const hold of adjustments.shelfLifeHolds) {
    addHintLine(cellKey(hold.fridge_id, hold.product_id), describeShelfLifeHold(hold))
  }

  const cellHints = new Map<string, string>()
  for (const [key, lines] of hintLines) cellHints.set(key, lines.join('\n'))
  return cellHints
}

/** "Salads: sold 6 + 9.5 still expected = 15.5 of forecast 20 (78%), quantity x 0.78". */
export function describeSpeedAdjustment(
  adjustment: SalesSpeedAdjustment,
  categoryName: string,
): string {
  const remaining = Number(adjustment.remaining_units)
  const projected = adjustment.sold_units + remaining
  const pacePercent = Math.round(Number(adjustment.pace) * PERCENT)
  return (
    `${categoryName}: sold ${adjustment.sold_units} + ${remaining.toFixed(1)} still expected = ` +
    `${projected.toFixed(1)} of forecast ${Number(adjustment.forecast_units).toFixed(1)} ` +
    `(${pacePercent}%), quantity x ${adjustment.factor}. ` +
    `Hourly profile: ${PROFILE_SOURCE_LABELS[adjustment.profile_source]}`
  )
}

/** "Not raised (7 -> 5): keeps 2 days, the delivery must last 3". */
export function describeShelfLifeHold(hold: ShelfLifeHold): string {
  return (
    `Not raised (${hold.raised_qty} -> ${hold.kept_qty}): keeps ${hold.shelf_life_days} days, ` +
    `the delivery must last ${hold.coverage_days}`
  )
}
