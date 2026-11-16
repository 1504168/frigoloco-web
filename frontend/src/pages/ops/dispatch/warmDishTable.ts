import type { WarmDishLine } from '@/pages/ops/dispatch/weekOverviewApi'

export interface WarmDishRow {
  key: string
  label: string
  qtyByDate: Map<string, number>
  total: number
}

export interface WarmDishProductGroup {
  product: WarmDishRow
  categoryName: string
  fridges: WarmDishRow[]
}

interface ProductGroupBuilder {
  group: WarmDishProductGroup
  fridgeRows: Map<number, WarmDishRow>
}

export interface WarmDishTable {
  deliveryDates: string[]
  productGroups: WarmDishProductGroup[]
  totals: WarmDishRow
}

/** Pivot warm dish lines into product groups (one row per fridge) x delivery day. */
export function buildWarmDishTable(lines: WarmDishLine[]): WarmDishTable {
  const deliveryDates = [...new Set(lines.map((line) => line.delivery_date))].sort()
  const totals = emptyRow('total', 'Total')
  const groupsByProduct = new Map<number, ProductGroupBuilder>()

  for (const line of lines) {
    let builder = groupsByProduct.get(line.product_id)
    if (builder === undefined) {
      builder = {
        group: {
          product: emptyRow(`product-${line.product_id}`, line.product_name),
          categoryName: line.category_name,
          fridges: [],
        },
        fridgeRows: new Map(),
      }
      groupsByProduct.set(line.product_id, builder)
    }
    let fridgeRow = builder.fridgeRows.get(line.fridge_id)
    if (fridgeRow === undefined) {
      fridgeRow = emptyRow(`fridge-${line.product_id}-${line.fridge_id}`, line.friendly_name)
      builder.fridgeRows.set(line.fridge_id, fridgeRow)
      builder.group.fridges.push(fridgeRow)
    }
    addQty(fridgeRow, line.delivery_date, line.qty)
    addQty(builder.group.product, line.delivery_date, line.qty)
    addQty(totals, line.delivery_date, line.qty)
  }
  const productGroups = [...groupsByProduct.values()].map((builder) => builder.group)

  return {
    deliveryDates,
    productGroups,
    totals,
  }
}

function emptyRow(key: string, label: string): WarmDishRow {
  return { key, label, qtyByDate: new Map(), total: 0 }
}

function addQty(row: WarmDishRow, deliveryDate: string, qty: number) {
  row.qtyByDate.set(deliveryDate, (row.qtyByDate.get(deliveryDate) ?? 0) + qty)
  row.total += qty
}
