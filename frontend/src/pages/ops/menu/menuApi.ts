import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from '@/lib/api'
import type { WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import type { MenuGrid } from '@/pages/ops/lib/types'

/** Prefix of every saved-menu query; invalidate it after a save. */
export const SAVED_MENU_QUERY_KEY = ['ops', 'menu', 'saved'] as const

const STOCK_BALANCES_STALE_MS = 60_000
const NOT_FOUND_STATUS = 404

/** GET /api/v1/menus/stock-balances item (schema: MenuStockBalanceOut). */
export interface MenuStockBalance {
  product_id: number
  in_stock_qty: number
  on_order_qty: number
}

export function menuKeyParams(key: WeekDayKey) {
  return {
    year: key.year,
    week: key.week,
    day_name: key.dayName,
  }
}

/**
 * The saved menu for the key, or, when none is saved yet, a blank menu holding
 * only the fridges delivered that weekday.
 */
export function useMenuForKey(key: WeekDayKey) {
  return useQuery({
    queryKey: [...SAVED_MENU_QUERY_KEY, key.year, key.week, key.dayName],
    queryFn: ({ signal }) => fetchMenuForKey(key, signal),
    retry: false,
  })
}

/** Warehouse in-stock and on-order units, by product id. */
export function useMenuStockBalances() {
  return useQuery({
    queryKey: ['ops', 'menu', 'stock-balances'],
    queryFn: ({ signal }) =>
      api.get<MenuStockBalance[]>('/api/v1/menus/stock-balances', { signal }),
    staleTime: STOCK_BALANCES_STALE_MS,
    select: (balances) => new Map(balances.map((balance) => [balance.product_id, balance])),
  })
}

async function fetchMenuForKey(key: WeekDayKey, signal: AbortSignal): Promise<MenuGrid> {
  const params = menuKeyParams(key)
  try {
    return await api.get<MenuGrid>('/api/v1/menus/saved', { params, signal })
  } catch (error) {
    const isNotSavedYet = error instanceof ApiError && error.status === NOT_FOUND_STATUS
    if (!isNotSavedYet) throw error
    return api.get<MenuGrid>('/api/v1/menus/blank', { params, signal })
  }
}
