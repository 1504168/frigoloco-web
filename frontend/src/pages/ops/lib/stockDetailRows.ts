import { EMPTY_PLACEHOLDER } from '@/lib/format'
import type { PlanningGridDetailRow } from '@/pages/ops/components/PlanningGrid'
import { useMenuStockBalances } from '@/pages/ops/menu/menuApi'

/** "In stock" and "On order" grid header rows from the warehouse stock balances. */
export function useStockDetailRows(): PlanningGridDetailRow[] {
  const stockQuery = useMenuStockBalances()
  return [
    {
      label: 'In stock',
      render: (productId) => stockQuery.data?.get(productId)?.in_stock_qty ?? EMPTY_PLACEHOLDER,
    },
    {
      label: 'On order',
      render: (productId) => stockQuery.data?.get(productId)?.on_order_qty ?? EMPTY_PLACEHOLDER,
    },
  ]
}
