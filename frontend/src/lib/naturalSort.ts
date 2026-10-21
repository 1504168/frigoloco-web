import type { Category } from '@/lib/types'

const NATURAL_COLLATOR = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
})

const UNCATEGORISED_NAMES = new Set(['uncategorised', 'uncategorized'])

/** Case-insensitive compare that orders embedded numbers by value ("Box 2" < "Box 10"). */
export function compareNatural(a: string, b: string): number {
  return NATURAL_COLLATOR.compare(a, b)
}

/** Categories by display_order, then natural name; "Uncategorised" always last. */
export function sortCategories<T extends Pick<Category, 'name' | 'display_order'>>(
  categories: T[],
): T[] {
  return [...categories].sort(compareCategories)
}

function compareCategories(
  a: Pick<Category, 'name' | 'display_order'>,
  b: Pick<Category, 'name' | 'display_order'>,
): number {
  const uncategorisedOrder = Number(isUncategorised(a)) - Number(isUncategorised(b))
  if (uncategorisedOrder !== 0) return uncategorisedOrder
  if (a.display_order !== b.display_order) return a.display_order - b.display_order
  return compareNatural(a.name, b.name)
}

function isUncategorised(category: Pick<Category, 'name'>): boolean {
  return UNCATEGORISED_NAMES.has(category.name.trim().toLowerCase())
}
