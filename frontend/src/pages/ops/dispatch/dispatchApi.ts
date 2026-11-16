import { api, downloadFile } from '@/lib/api'
import type { WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import type {
  DispatchMatrix,
  DispatchRead,
  GridLineItem,
  WarehouseStockCut,
} from '@/pages/ops/lib/types'

/** GET /dispatches/{id}/matrix: the grid plus the cost at snapshot prices once dispatched. */
export interface SavedDispatchMatrix extends DispatchMatrix {
  dispatched_cost_total: string | null
}

export interface SavedDispatch {
  saved: DispatchRead
  matrix: SavedDispatchMatrix
}

/** Query key prefix of every cached dispatch read; invalidate it after a write. */
export const DISPATCH_QUERY_KEY = ['ops', 'dispatch'] as const

export type QuantityLine = Pick<GridLineItem, 'fridge_id' | 'product_id' | 'qty'>

/** A fit-to-stock cut; `in_stock` includes `on_order` units when orders were included. */
export interface DispatchStockCut extends WarehouseStockCut {
  on_order: number
}

/** Units of a product that only fit because a purchase order is due in time. */
export interface ProductOrderUse {
  product_id: number
  units_from_orders: number
}

/** POST /dispatches/fit-to-stock response (schema: StockFitOut). */
export interface StockFit {
  /** The request lines in the same order, cut to the warehouse stock. */
  lines: QuantityLine[]
  cuts: DispatchStockCut[]
  order_uses: ProductOrderUse[]
}

/** Load the saved dispatch for a key with its matrix; throws ApiError 404 when none. */
export async function fetchSavedDispatch(
  key: WeekDayKey,
  signal?: AbortSignal,
): Promise<SavedDispatch> {
  const saved = await api.get<DispatchRead>('/api/v1/dispatches/saved', {
    params: { year: key.year, week: key.week, day_name: key.dayName },
    signal,
  })
  const matrix = await api.get<SavedDispatchMatrix>(`/api/v1/dispatches/${saved.id}/matrix`, {
    signal,
  })
  return { saved, matrix }
}

/**
 * Order-independent fingerprint of the planned quantities, so the grid on
 * screen can be compared with what is saved.
 */
export function quantitiesSignature(lines: QuantityLine[]): string {
  const lineKeys = lines.map((line) => `${line.fridge_id}:${line.product_id}:${line.qty}`)
  return lineKeys.sort().join('|')
}

/** Download the dispatch Excel file through the browser. */
export function downloadDispatchExcel(dispatch: DispatchRead): Promise<void> {
  return downloadFile(
    `/api/v1/dispatches/${dispatch.id}/export.xlsx`,
    `dispatch_${dispatch.delivery_date}.xlsx`,
  )
}

/**
 * Preview of cutting planned lines to the warehouse stock; nothing is saved. With
 * `includeOrdersDueBy` (a yyyy-mm-dd delivery date) pending orders due by then count too.
 */
export function fitLinesToStock(
  lines: QuantityLine[],
  includeOrdersDueBy: string | null,
): Promise<StockFit> {
  const requestLines = lines.map(({ fridge_id, product_id, qty }) => ({
    fridge_id,
    product_id,
    qty,
  }))
  return api.post<StockFit>('/api/v1/dispatches/fit-to-stock', {
    lines: requestLines,
    include_orders_due_by: includeOrdersDueBy,
  })
}

/** The lines whose quantity the fit lowered, with their new quantity. */
export function linesCutByStockFit(original: QuantityLine[], stockFit: StockFit): QuantityLine[] {
  return stockFit.lines.filter((fittedLine, position) => fittedLine.qty !== original[position].qty)
}

export function totalUnitsCut(cuts: WarehouseStockCut[]): number {
  return cuts.reduce((total, stockCut) => total + stockCut.cut, 0)
}

export function totalUnitsFromOrders(orderUses: ProductOrderUse[]): number {
  return orderUses.reduce((total, orderUse) => total + orderUse.units_from_orders, 0)
}

/** Toast text when a fit found nothing to cut. */
export function describeNothingToCut(orderUses: ProductOrderUse[]): string {
  const unitsFromOrders = totalUnitsFromOrders(orderUses)
  if (unitsFromOrders === 0) return 'Everything fits the warehouse stock: nothing to cut.'
  return (
    `Everything fits, but ${unitsFromOrders} units of ${orderUses.length} products ` +
    'come from purchase orders that must arrive before you dispatch.'
  )
}
