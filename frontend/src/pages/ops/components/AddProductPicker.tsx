import * as React from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Product } from '@/lib/types'

const UNASSIGNED = '__unassigned__'

export interface AddProductPickerProps {
  /** Full catalogue, loaded once and filtered entirely client-side. */
  products: Product[]
  categoryName: (categoryId: number) => string
  supplierName: (supplierId: number) => string
  /** Product ids already on the grid (excluded from the product select). */
  existingProductIds: Set<number>
  onAdd: (product: Product) => void
}

/**
 * Cascading category → supplier → product picker. All three levels filter the
 * in-memory catalogue locally (no per-change API calls), matching the Excel
 * "add product" flow. Supplier-less products fall into an "Unassigned" bucket.
 */
export function AddProductPicker({
  products,
  categoryName,
  supplierName,
  existingProductIds,
  onAdd,
}: AddProductPickerProps) {
  const [categoryId, setCategoryId] = React.useState<string>('')
  const [supplierId, setSupplierId] = React.useState<string>('')
  const [productId, setProductId] = React.useState<string>('')

  // Distinct categories present in the catalogue, sorted by their label.
  const categoryOptions = React.useMemo(() => {
    const ids = Array.from(new Set(products.map((product) => product.category_id)))
    return ids
      .map((id) => ({ id, label: categoryName(id) }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [products, categoryName])

  // Suppliers within the chosen category.
  const supplierOptions = React.useMemo(() => {
    if (!categoryId) return []
    const inCategory = products.filter((product) => String(product.category_id) === categoryId)
    const ids = new Set<string>()
    for (const product of inCategory) {
      ids.add(product.supplier_id === null ? UNASSIGNED : String(product.supplier_id))
    }
    return Array.from(ids)
      .map((value) => ({
        value,
        label: value === UNASSIGNED ? 'Unassigned' : supplierName(Number(value)),
      }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [products, categoryId, supplierName])

  // Products within the chosen category + supplier, minus those already on the grid.
  const productOptions = React.useMemo(() => {
    if (!categoryId || !supplierId) return []
    return products
      .filter((product) => {
        if (String(product.category_id) !== categoryId) return false
        const bucket = product.supplier_id === null ? UNASSIGNED : String(product.supplier_id)
        if (bucket !== supplierId) return false
        return !existingProductIds.has(product.id)
      })
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [products, categoryId, supplierId, existingProductIds])

  function handleCategoryChange(next: string) {
    setCategoryId(next)
    setSupplierId('')
    setProductId('')
  }

  function handleSupplierChange(next: string) {
    setSupplierId(next)
    setProductId('')
  }

  function handleAdd() {
    const product = products.find((entry) => String(entry.id) === productId)
    if (!product) return
    onAdd(product)
    setProductId('')
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-1">
        <span className="text-xs font-medium text-muted-foreground">Category</span>
        <Select value={categoryId} onValueChange={handleCategoryChange}>
          <SelectTrigger>
            <SelectValue placeholder="Choose a category" />
          </SelectTrigger>
          <SelectContent>
            {categoryOptions.map((option) => (
              <SelectItem key={option.id} value={String(option.id)}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </label>

      <label className="space-y-1">
        <span className="text-xs font-medium text-muted-foreground">Supplier</span>
        <Select value={supplierId} onValueChange={handleSupplierChange} disabled={!categoryId}>
          <SelectTrigger>
            <SelectValue placeholder={categoryId ? 'Choose a supplier' : 'Pick a category first'} />
          </SelectTrigger>
          <SelectContent>
            {supplierOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </label>

      <label className="space-y-1 sm:col-span-2">
        <span className="text-xs font-medium text-muted-foreground">Product</span>
        <Select value={productId} onValueChange={setProductId} disabled={!supplierId}>
          <SelectTrigger>
            <SelectValue placeholder={supplierId ? 'Choose a product' : 'Pick a supplier first'} />
          </SelectTrigger>
          <SelectContent>
            {productOptions.length === 0 ? (
              <div className="px-3 py-2 text-xs text-muted-foreground">
                No selectable products in this group.
              </div>
            ) : (
              productOptions.map((product) => (
                <SelectItem key={product.id} value={String(product.id)}>
                  {product.name} · {product.code}
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>
      </label>

      <div className="sm:col-span-2">
        <Button onClick={handleAdd} disabled={!productId} className="w-full">
          <Plus className="h-4 w-4" />
          Add product to grid
        </Button>
      </div>
    </div>
  )
}
