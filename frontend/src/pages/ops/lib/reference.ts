/**
 * Shared reference-data hooks for the OPS domain. These back the pipeline grids:
 * fridge/category name lookups, the full product catalogue (loaded once and
 * filtered client-side by the Add-Product picker), suppliers, product scores,
 * and the configurable menu columns-per-category setting.
 */
import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '@/lib/api'
import { formatFridgeName } from '@/lib/format'
import {
  REFERENCE_CATEGORIES_KEY,
  REFERENCE_FRIDGES_KEY,
  REFERENCE_FRIDGES_LIMIT,
} from '@/lib/query-keys'
import type { Product } from '@/lib/types'
import type {
  Category,
  Fridge,
  ScorecardItem,
  Supplier,
} from '@/pages/ops/lib/types'

const REFERENCE_STALE_MS = 5 * 60_000
const PRODUCTS_PAGE_SIZE = 500
// Scorecard window for the grid's score row: the stored 365-day scores menu allocation uses.
const ALLOCATION_SCORE_WINDOW_DAYS = 365

/** Map of fridge id -> friendly name. Loads all active fridges once. */
export function useFridgeMap() {
  return useQuery({
    queryKey: REFERENCE_FRIDGES_KEY,
    queryFn: ({ signal }) =>
      api.get<Page<Fridge>>('/api/v1/fridges', {
        params: { limit: REFERENCE_FRIDGES_LIMIT },
        signal,
      }),
    staleTime: REFERENCE_STALE_MS,
    select: (page) => new Map(page.items.map((fridge) => [fridge.id, formatFridgeName(fridge)])),
  })
}

/** Ordered category list (by display_order) plus an id -> name map. */
export function useCategories() {
  return useQuery({
    queryKey: REFERENCE_CATEGORIES_KEY,
    queryFn: ({ signal }) => api.get<Category[]>('/api/v1/categories', { signal }),
    staleTime: REFERENCE_STALE_MS,
    select: (items) => {
      const ordered = [...items].sort((a, b) => a.display_order - b.display_order)
      const byId = new Map(items.map((category) => [category.id, category.name]))
      return { ordered, byId }
    },
  })
}

/** Display name of a category, or null when no category is given. */
export function useCategoryName(categoryId: number | null): string | null {
  const categoriesQuery = useCategories()
  if (categoryId === null) return null
  return categoriesQuery.data?.byId.get(categoryId) ?? `Category #${categoryId}`
}

/** Map of supplier id -> name. Loads all suppliers once. */
export function useSupplierMap() {
  return useQuery({
    queryKey: ['ops', 'suppliers', 'map'],
    queryFn: ({ signal }) =>
      api.get<Page<Supplier>>('/api/v1/suppliers', { params: { limit: 500 }, signal }),
    staleTime: REFERENCE_STALE_MS,
    select: (page) => new Map(page.items.map((supplier) => [supplier.id, supplier.name])),
  })
}

/**
 * The full product catalogue, loaded once across all pages (the API caps a page
 * at 500 rows, so this walks every offset). Returned as both the flat list and
 * an id -> product map so grids can look up code/prices/VAT/shelf-life locally
 * without a request per cell.
 */
export function useProductCatalogue() {
  return useQuery({
    queryKey: ['ops', 'products', 'catalogue'],
    staleTime: REFERENCE_STALE_MS,
    queryFn: async ({ signal }) => {
      const all: Product[] = []
      let offset = 0
      // Guard against an unbounded loop if `total` is ever missing.
      for (let guard = 0; guard < 50; guard += 1) {
        const page = await api.get<Page<Product>>('/api/v1/products', {
          params: { limit: PRODUCTS_PAGE_SIZE, offset },
          signal,
        })
        all.push(...page.items)
        offset += PRODUCTS_PAGE_SIZE
        if (offset >= page.total || page.items.length === 0) break
      }
      return all
    },
    select: (items) => ({
      items,
      byId: new Map(items.map((product) => [product.id, product])),
    }),
  })
}

/** Map of product id -> stored 365-day final score (the same scores menu allocation uses). */
export function useScoreMap() {
  return useQuery({
    queryKey: ['ops', 'scores', 'map'],
    staleTime: REFERENCE_STALE_MS,
    queryFn: async ({ signal }) => {
      const all: ScorecardItem[] = []
      let offset = 0
      for (let guard = 0; guard < 50; guard += 1) {
        const page = await api.get<Page<ScorecardItem>>('/api/v1/rating/scorecard', {
          params: { limit: PRODUCTS_PAGE_SIZE, offset, window_days: ALLOCATION_SCORE_WINDOW_DAYS },
          signal,
        })
        all.push(...page.items)
        offset += PRODUCTS_PAGE_SIZE
        if (offset >= page.total || page.items.length === 0) break
      }
      return all
    },
    // A missing scorecard is non-fatal - the score row simply shows placeholders.
    retry: false,
    select: (items) => new Map(items.map((item) => [item.product_id, item.final_score])),
  })
}
