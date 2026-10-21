import * as React from 'react'
import { Plus } from 'lucide-react'
import { CategoryFilter } from '@/components/filters/CategoryFilter'
import { ProductSearchInput } from '@/components/filters/ProductSearchInput'
import { SupplierFilter } from '@/components/filters/SupplierFilter'
import { matchesProductSearch } from '@/components/filters/productSearch'
import { Button } from '@/components/ui/button'
import { compareNatural } from '@/lib/naturalSort'
import type { Product } from '@/lib/types'

const ACTIVE_STATUS = 'active'
const MAX_LISTED_PRODUCTS = 50
const PRODUCT_LIST_CLASS =
  'max-h-80 divide-y divide-border overflow-y-auto rounded-lg border border-border'

export interface AddProductPickerProps {
  /** Full catalogue, loaded once and filtered entirely client-side. */
  products: Product[]
  supplierName: (supplierId: number) => string
  /** Product ids already on the grid (not offered again). */
  existingProductIds: Set<number>
  onAdd: (product: Product) => void
}

/**
 * Category, supplier and search filters over the active catalogue, with an Add
 * button per product. Inactive and cancelled products (effective status) and
 * products already on the grid are not offered.
 */
export function AddProductPicker({
  products,
  supplierName,
  existingProductIds,
  onAdd,
}: AddProductPickerProps) {
  const [categoryId, setCategoryId] = React.useState<number | null>(null)
  const [supplierId, setSupplierId] = React.useState<number | null>(null)
  const [search, setSearch] = React.useState('')

  const matchingProducts = React.useMemo(
    () =>
      products
        .filter(
          (product) =>
            product.effective_status === ACTIVE_STATUS &&
            !existingProductIds.has(product.id) &&
            (categoryId === null || product.category_id === categoryId) &&
            (supplierId === null || product.supplier_id === supplierId) &&
            matchesProductSearch(search, product.code, product.name),
        )
        .sort((a, b) => compareNatural(a.name, b.name)),
    [products, existingProductIds, categoryId, supplierId, search],
  )
  const listedProducts = matchingProducts.slice(0, MAX_LISTED_PRODUCTS)
  const hiddenProductCount = matchingProducts.length - listedProducts.length

  function handleCategoryChange(nextCategoryId: number | null) {
    setCategoryId(nextCategoryId)
    setSupplierId(null)
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <CategoryFilter
          value={categoryId}
          onChange={handleCategoryChange}
          className="h-9 w-full"
        />
        <SupplierFilter
          value={supplierId}
          onChange={setSupplierId}
          categoryId={categoryId}
          className="h-9 w-full"
        />
        <ProductSearchInput
          onSearchChange={setSearch}
          className="w-full sm:col-span-2"
        />
      </div>

      <ul className={PRODUCT_LIST_CLASS}>
        {listedProducts.length === 0 ? (
          <li className="px-3 py-4 text-center text-xs text-muted-foreground">
            No active products match these filters.
          </li>
        ) : null}
        {listedProducts.map((product) => (
          <li
            key={product.id}
            className="flex items-center justify-between gap-3 px-3 py-2"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{product.name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {product.code} ·{' '}
                {product.supplier_id === null ? 'Unassigned' : supplierName(product.supplier_id)}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onAdd(product)}
            >
              <Plus className="h-4 w-4" />
              Add
            </Button>
          </li>
        ))}
      </ul>
      {hiddenProductCount > 0 ? (
        <p className="text-xs text-muted-foreground">
          {hiddenProductCount} more match. Narrow the filters or search to see them.
        </p>
      ) : null}
    </div>
  )
}
