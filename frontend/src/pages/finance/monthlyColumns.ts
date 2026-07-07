/**
 * Column definitions for the monthly P&L table. Which columns are meaningful
 * depends on the dimension (verified live against the API):
 *   - client:   sales, pos_fee, fee_share, service_additionals, logistics_share
 *   - supplier/category: rfid_fee only (sales/pos_fee come back null)
 * FM% is computed client-side as food_margin ÷ sales.
 */
import { formatEuro } from '@/lib/format'
import type { MonthlyAnalysisRow, MonthlyDimension } from '@/pages/finance/types'
import { formatPercent, safeRatio, toNumber } from '@/pages/finance/utils'

export interface MonthlyColumn {
  id: string
  header: string
  /** Numeric value for a row (null when not applicable). Drives totals + align. */
  value: (row: MonthlyAnalysisRow) => number | null
  /** Rendered cell text. */
  render: (row: MonthlyAnalysisRow) => string
  /** How the totals-row cell is rendered from the column total. */
  renderTotal?: (rows: MonthlyAnalysisRow[]) => string
  /** Emphasize the value with good/critical sign colouring. */
  signed?: boolean
}

const euroCol = (
  id: string,
  header: string,
  accessor: (row: MonthlyAnalysisRow) => string | null,
  signed = false,
): MonthlyColumn => ({
  id,
  header,
  signed,
  value: (row) => (accessor(row) === null ? null : toNumber(accessor(row))),
  render: (row) => (accessor(row) === null ? '—' : formatEuro(accessor(row))),
})

const foodMarginPctCol: MonthlyColumn = {
  id: 'fm_pct',
  header: 'FM %',
  value: (row) => safeRatio(toNumber(row.food_margin), toNumber(row.sales)),
  render: (row) => formatPercent(safeRatio(toNumber(row.food_margin), toNumber(row.sales))),
  renderTotal: (rows) => {
    const margin = rows.reduce((sum, row) => sum + toNumber(row.food_margin), 0)
    const sales = rows.reduce((sum, row) => sum + toNumber(row.sales), 0)
    return formatPercent(safeRatio(margin, sales))
  },
}

const CLIENT_COLUMNS: MonthlyColumn[] = [
  euroCol('sales', 'Sales turnover', (row) => row.sales),
  euroCol('food_margin', 'Food margin', (row) => row.food_margin, true),
  foodMarginPctCol,
  euroCol('service_additionals', 'Service add.', (row) => row.service_additionals),
  euroCol('logistics_share', 'Logistics', (row) => row.logistics_share),
  euroCol('pos_fee', 'POS & SW', (row) => row.pos_fee),
  euroCol('fee_share', 'Client fee /mo', (row) => row.fee_share),
  euroCol('net_margin', 'Net margin', (row) => row.net_margin, true),
]

const SUPPLIER_CATEGORY_COLUMNS: MonthlyColumn[] = [
  euroCol('sales', 'Sales turnover', (row) => row.sales),
  euroCol('food_margin', 'Food margin', (row) => row.food_margin, true),
  foodMarginPctCol,
  euroCol('rfid_fee', 'RFID & transaction', (row) => row.rfid_fee),
  euroCol('net_margin', 'Net margin', (row) => row.net_margin, true),
]

/** The name column header per dimension. */
export const NAME_HEADER: Record<MonthlyDimension, string> = {
  client: 'Fridge',
  supplier: 'Supplier',
  category: 'Category',
}

export function columnsForDimension(dimension: MonthlyDimension): MonthlyColumn[] {
  return dimension === 'client' ? CLIENT_COLUMNS : SUPPLIER_CATEGORY_COLUMNS
}
