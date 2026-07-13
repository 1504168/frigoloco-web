/**
 * Query keys for the cross-domain reference reads: the lookup lists that several
 * page domains fetch from the same endpoint, with the same params and the same
 * shape. Declaring them once is what makes sharing a single cache entry across
 * pages deliberate rather than an accidental collision. Keys that belong to one
 * domain stay in that domain, namespaced by it (e.g. ['supply', 'fridges']).
 */

/** GET /api/v1/categories: the full category list (bare array). */
export const REFERENCE_CATEGORIES_KEY = ['reference', 'categories'] as const

/** GET /api/v1/fridges: every fridge, used for id -> name lookups and pickers. */
export const REFERENCE_FRIDGES_KEY = ['reference', 'fridges', 'all'] as const

/** Page size shared by the reference fridge fetchers so they hit one cache entry. */
export const REFERENCE_FRIDGES_LIMIT = 500
