import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '@/lib/api'
import { compareNatural } from '@/lib/naturalSort'
import type { Supplier } from '@/lib/types'

const SUPPLIER_OPTIONS_LIMIT = 500
const SUPPLIER_OPTIONS_STALE_MS = 5 * 60_000

/**
 * Suppliers sorted naturally by name. With `categoryId`, only suppliers that have
 * at least one product in that category (GET /api/v1/suppliers?category_id=).
 */
export function useSupplierOptions(categoryId: number | null = null) {
  return useQuery({
    queryKey: ['filters', 'suppliers', categoryId],
    queryFn: ({ signal }) =>
      api.get<Page<Supplier>>('/api/v1/suppliers', {
        params: {
          limit: SUPPLIER_OPTIONS_LIMIT,
          category_id: categoryId,
        },
        signal,
      }),
    staleTime: SUPPLIER_OPTIONS_STALE_MS,
    select: (page) => [...page.items].sort((a, b) => compareNatural(a.name, b.name)),
  })
}
