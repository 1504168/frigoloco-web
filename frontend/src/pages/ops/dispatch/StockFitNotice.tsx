import { PackageMinus } from 'lucide-react'
import {
  totalUnitsCut,
  totalUnitsFromOrders,
  type DispatchStockCut,
  type ProductOrderUse,
} from '@/pages/ops/dispatch/dispatchApi'
import type { WarehouseStockCut } from '@/pages/ops/lib/types'

/** The cuts the user applied and the units that rely on purchase orders. */
export interface AppliedStockFit {
  cuts: DispatchStockCut[]
  orderUses: ProductOrderUse[]
}

// The menu import also shows this notice; its cuts never include orders.
type NoticeStockCut = WarehouseStockCut & { on_order?: number }

interface StockFitNoticeProps {
  cuts: NoticeStockCut[]
  orderUses?: ProductOrderUse[]
  productName: (productId: number) => string
}

const NO_ORDER_USES: ProductOrderUse[] = []
const ORDERED_UNITS_WARNING = 'units come from purchase orders that must arrive before you dispatch'

/** What "Fit to stock" cut, and how much of the planned stock is still on order. */
export function StockFitNotice({
  cuts,
  orderUses = NO_ORDER_USES,
  productName,
}: StockFitNoticeProps) {
  if (cuts.length === 0 && orderUses.length === 0) return null
  const unitsCut = totalUnitsCut(cuts)
  const unitsFromOrders = totalUnitsFromOrders(orderUses)
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-xs text-foreground"
    >
      <PackageMinus className="mt-0.5 h-4 w-4 shrink-0" />
      <details>
        <summary className="cursor-pointer">
          Fit to stock cut {unitsCut} units of {cuts.length} products (left unallocated)
          {unitsFromOrders > 0 ? `; ${unitsFromOrders} ${ORDERED_UNITS_WARNING}` : null}
        </summary>
        <ul className="mt-1 list-disc pl-5">
          {cuts.map((stockCut) => (
            <li key={`cut-${stockCut.product_id}`}>
              {productName(stockCut.product_id)}: asked {stockCut.requested}, available{' '}
              {stockCut.in_stock}
              {stockCut.on_order ? ` (${stockCut.on_order} on order)` : null}, cut{' '}
              {stockCut.cut}
            </li>
          ))}
          {orderUses.map((orderUse) => (
            <li key={`order-${orderUse.product_id}`}>
              {productName(orderUse.product_id)}: {orderUse.units_from_orders} units from orders
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}
