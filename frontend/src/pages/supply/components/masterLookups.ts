import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '@/lib/api'
import { compareNatural } from '@/lib/naturalSort'
import { REFERENCE_FRIDGES_KEY, REFERENCE_FRIDGES_LIMIT } from '@/lib/query-keys'
import type { Fridge } from '@/lib/types'
import type { Client } from '../types'

const LOOKUP_STALE_MS = 5 * 60_000
const ALL_ROWS_LIMIT = 500

/** Every client sorted by name, for pickers and id -> name lookups. */
export function useAllClients() {
  return useQuery({
    queryKey: ['supply', 'clients', 'lookup'],
    queryFn: ({ signal }) =>
      api.get<Page<Client>>('/api/v1/clients', { params: { limit: ALL_ROWS_LIMIT }, signal }),
    staleTime: LOOKUP_STALE_MS,
    select: (page) => [...page.items].sort((a, b) => compareNatural(a.name, b.name)),
  })
}

/** Every fridge (any status), shared with the other pages through REFERENCE_FRIDGES_KEY. */
export function useAllFridges() {
  return useQuery({
    queryKey: REFERENCE_FRIDGES_KEY,
    queryFn: ({ signal }) =>
      api.get<Page<Fridge>>('/api/v1/fridges', {
        params: { limit: REFERENCE_FRIDGES_LIMIT },
        signal,
      }),
    staleTime: LOOKUP_STALE_MS,
    select: (page) =>
      [...page.items].sort((a, b) => compareNatural(a.friendly_name, b.friendly_name)),
  })
}

/** GET /api/v1/product-tags: the suggested tags plus every tag already used on a product. */
export function useProductTagOptions() {
  return useQuery({
    queryKey: ['supply', 'product-tags'],
    queryFn: ({ signal }) => api.get<string[]>('/api/v1/product-tags', { signal }),
    staleTime: LOOKUP_STALE_MS,
  })
}

/** "contains_pork" -> "Contains pork". */
export function productTagLabel(tag: string): string {
  const words = tag.replaceAll('_', ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
