import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '@/lib/api'
import { compareNatural } from '@/lib/naturalSort'
import type { Supplier, SupplierCategoryLink } from '@/lib/types'

const SUPPLIER_OPTIONS_LIMIT = 500
const SUPPLIER_OPTIONS_STALE_MS = 5 * 60_000

/**
 * Suppliers sorted naturally by name. With `categoryId`, only suppliers that have
 * at least one product in that category. Both lists load once and are filtered here,
 * so changing the category never waits on the server.
 */
export function useSupplierOptions(categoryId: number | null = null) {
  const suppliersQuery = useQuery({
    queryKey: ['filters', 'suppliers'],
    queryFn: ({ signal }) =>
      api.get<Page<Supplier>>('/api/v1/suppliers', {
        params: { limit: SUPPLIER_OPTIONS_LIMIT },
        signal,
      }),
    staleTime: SUPPLIER_OPTIONS_STALE_MS,
    select: (page) => [...page.items].sort((a, b) => compareNatural(a.name, b.name)),
  })
  const linksQuery = useQuery({
    queryKey: ['filters', 'supplier-category-links'],
    queryFn: ({ signal }) =>
      api.get<SupplierCategoryLink[]>('/api/v1/suppliers/category-links', { signal }),
    staleTime: SUPPLIER_OPTIONS_STALE_MS,
  })

  const allSuppliers = suppliersQuery.data
  if (categoryId === null || allSuppliers === undefined) {
    return { data: allSuppliers }
  }
  if (linksQuery.data === undefined) {
    return { data: undefined }
  }
  const supplierIdsInCategory = new Set(
    linksQuery.data
      .filter((link) => link.category_id === categoryId)
      .map((link) => link.supplier_id),
  )
  return { data: allSuppliers.filter((supplier) => supplierIdsInCategory.has(supplier.id)) }
}
