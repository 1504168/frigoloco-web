/**
 * Column definitions for the monthly P&L table. Which columns are meaningful
 * depends on the dimension (verified live against the API):
 *   - client:   sales, pos_fee, fee_share, service_additionals, logistics_share,
 *               fridge count
 *   - fridge:   the client columns, with the fridge's client instead of a count
 *   - supplier/category: rfid_fee only (sales/pos_fee come back null)
 * FM% is computed client-side as food_margin ÷ sales ex VAT (both ex VAT).
 */
import { EMPTY_PLACEHOLDER, formatEuro } from '@/lib/format'
import type { MonthlyAnalysisRow, MonthlyDimension } from '@/pages/finance/types'
import { formatCount, formatPercent, safeRatio, toNumber } from '@/pages/finance/utils'

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
  /** Text columns read left-aligned; numbers stay right-aligned. */
  alignLeft?: boolean
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
  render: (row) => (accessor(row) === null ? EMPTY_PLACEHOLDER : formatEuro(accessor(row))),
})

const foodMarginPctCol: MonthlyColumn = {
  id: 'fm_pct',
  header: 'FM %',
  value: (row) => safeRatio(toNumber(row.food_margin), toNumber(row.sales_ex_vat)),
  render: (row) => formatPercent(safeRatio(toNumber(row.food_margin), toNumber(row.sales_ex_vat))),
  renderTotal: (rows) => {
    const margin = rows.reduce((sum, row) => sum + toNumber(row.food_margin), 0)
    const salesExVat = rows.reduce((sum, row) => sum + toNumber(row.sales_ex_vat), 0)
    return formatPercent(safeRatio(margin, salesExVat))
  },
}

const fridgeCountCol: MonthlyColumn = {
  id: 'fridge_count',
  header: 'Fridges',
  value: (row) => row.fridge_count,
  render: (row) => (row.fridge_count === null ? EMPTY_PLACEHOLDER : formatCount(row.fridge_count)),
  renderTotal: (rows) => formatCount(rows.reduce((sum, row) => sum + (row.fridge_count ?? 0), 0)),
}

const clientNameCol: MonthlyColumn = {
  id: 'client_name',
  header: 'Client',
  alignLeft: true,
  value: () => null,
  render: (row) => row.client_name ?? EMPTY_PLACEHOLDER,
  renderTotal: () => '',
}

const CLIENT_COST_COLUMNS: MonthlyColumn[] = [
  euroCol('sales_ex_vat', 'Sales ex VAT', (row) => row.sales_ex_vat),
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
  client: 'Client',
  fridge: 'Fridge',
  supplier: 'Supplier',
  category: 'Category',
}

const COLUMNS_BY_DIMENSION: Record<MonthlyDimension, MonthlyColumn[]> = {
  client: [fridgeCountCol, ...CLIENT_COST_COLUMNS],
  fridge: [clientNameCol, ...CLIENT_COST_COLUMNS],
  supplier: SUPPLIER_CATEGORY_COLUMNS,
  category: SUPPLIER_CATEGORY_COLUMNS,
}

export function columnsForDimension(dimension: MonthlyDimension): MonthlyColumn[] {
  return COLUMNS_BY_DIMENSION[dimension]
}
