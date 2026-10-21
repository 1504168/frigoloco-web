import type { Product } from '@/lib/types'
import type { GridLineItem } from '@/pages/ops/lib/types'

const CENTS_PER_EURO = 100

/** Menu value totals in euro cents. Purchase prices exclude VAT; sales prices include it. */
export interface MenuTotals {
  units: number
  purchaseCents: number
  salesInclVatCents: number
  salesExVatCents: number
  marginExVatCents: number
  /** Margin over sales ex VAT, as a fraction; null when there are no sales. */
  marginFraction: number | null
}

/** Totals of grid quantities x catalogue prices. */
export function computeMenuTotals(
  lines: GridLineItem[],
  productsById: Map<number, Product>,
): MenuTotals {
  let units = 0
  let purchaseCents = 0
  let salesInclVatCents = 0
  let salesExVatCents = 0
  for (const line of lines) {
    const product = productsById.get(line.product_id)
    if (product === undefined) continue
    const unitSalesCents = toCents(product.sales_price)
    units += line.qty
    purchaseCents += line.qty * toCents(product.purchase_price)
    salesInclVatCents += line.qty * unitSalesCents
    salesExVatCents += (line.qty * unitSalesCents) / (1 + Number(product.vat_rate))
  }
  const roundedSalesExVatCents = Math.round(salesExVatCents)
  const marginExVatCents = roundedSalesExVatCents - purchaseCents
  return {
    units,
    purchaseCents,
    salesInclVatCents,
    salesExVatCents: roundedSalesExVatCents,
    marginExVatCents,
    marginFraction: roundedSalesExVatCents > 0 ? marginExVatCents / roundedSalesExVatCents : null,
  }
}

export function centsToEuros(cents: number): number {
  return cents / CENTS_PER_EURO
}

function toCents(euroAmount: string): number {
  return Math.round(Number(euroAmount) * CENTS_PER_EURO)
}
