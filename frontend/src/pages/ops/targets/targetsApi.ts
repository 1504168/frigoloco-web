import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/** Prefix of every refill-target query; invalidate it after a save or a copy. */
export const TARGETS_QUERY_KEY = ['ops', 'product-targets'] as const

/** GET /menus/product-targets item (schema: TargetRead). */
export interface ProductTarget {
  fridge_id: number
  product_id: number
  target_qty: number
  updated_at: string
}

export interface TargetProduct {
  product_id: number
  product_code: string
  product_name: string
}

/** GET /menus/product-targets/products item (schema: TargetCategoryOut). */
export interface TargetCategory {
  category_id: number
  category_name: string
  products: TargetProduct[]
}

export interface TargetItem {
  product_id: number
  target_qty: number
}

export function useTargetCategories() {
  return useQuery({
    queryKey: [...TARGETS_QUERY_KEY, 'products'],
    queryFn: ({ signal }) =>
      api.get<TargetCategory[]>('/api/v1/menus/product-targets/products', { signal }),
  })
}

export function useFridgeTargets(fridgeId: number | null) {
  return useQuery({
    queryKey: [...TARGETS_QUERY_KEY, 'fridge', fridgeId],
    queryFn: ({ signal }) =>
      api.get<ProductTarget[]>('/api/v1/menus/product-targets', {
        params: { fridge_id: fridgeId },
        signal,
      }),
    enabled: fridgeId !== null,
  })
}

export function saveFridgeTargets(fridgeId: number, items: TargetItem[]) {
  return api.put<ProductTarget[]>(
    '/api/v1/menus/product-targets',
    { items },
    { params: { fridge_id: fridgeId } },
  )
}

export function copyFridgeTargets(fromFridgeId: number, toFridgeId: number) {
  return api.post<ProductTarget[]>('/api/v1/menus/product-targets/copy', undefined, {
    params: { from_fridge_id: fromFridgeId, to_fridge_id: toFridgeId },
  })
}
