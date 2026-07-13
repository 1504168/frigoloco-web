/**
 * Shared client-side state for the Excel-like Menu/Dispatch planning grids.
 * Both stages consume the same MenuGridOut/DispatchMatrix shape, so the grid
 * state (fridges, category→product columns, editable quantities, locally-added
 * products) and the product-metadata lookup live here and are reused by both
 * pages - the only differences are the import/save endpoints they call.
 */
import * as React from 'react'
import type { Product } from '@/lib/types'
import type { ProductMeta } from '@/pages/ops/components/PlanningGrid'
import {
  useCategories,
  useProductCatalogue,
  useScoreMap,
  useSupplierMap,
} from '@/pages/ops/lib/reference'
import type {
  GridCategory,
  GridCell,
  GridFridge,
  GridLineItem,
  GridProduct,
} from '@/pages/ops/lib/types'

/** The minimal grid payload both menus/* and dispatches/* return. */
export interface GridLike {
  fridges: GridFridge[]
  products: GridProduct[]
  categories: GridCategory[]
  cells: GridCell[]
}

function cellKey(fridgeId: number, productId: number): string {
  return `${fridgeId}:${productId}`
}

/**
 * Builds the per-product detail metadata (code, prices, VAT, margin, score,
 * shelf life, supplier) shown in the grid's header rows, combining the product
 * catalogue, the rating scorecard, and the supplier name map. Returns the
 * lookup plus a loading flag for the reference queries.
 */
export function useProductMeta() {
  const catalogueQuery = useProductCatalogue()
  const scoreQuery = useScoreMap()
  const supplierQuery = useSupplierMap()

  const meta = React.useCallback(
    (productId: number): ProductMeta | null => {
      const product = catalogueQuery.data?.byId.get(productId)
      if (!product) return null
      const purchase = Number(product.purchase_price)
      const sales = Number(product.sales_price)
      const marginPct = sales > 0 ? (sales - purchase) / sales : null
      return {
        productName: product.name,
        code: product.code,
        purchasePrice: product.purchase_price,
        salesPrice: product.sales_price,
        vatRate: product.vat_rate,
        marginPct,
        score: scoreQuery.data?.get(productId) ?? null,
        shelfLifeDays: product.shelf_life_days,
        supplierId: product.supplier_id,
        supplierName:
          product.supplier_id === null
            ? 'Unassigned'
            : supplierQuery.data?.get(product.supplier_id) ?? `Supplier #${product.supplier_id}`,
      }
    },
    [catalogueQuery.data, scoreQuery.data, supplierQuery.data],
  )

  return {
    meta,
    isLoading: catalogueQuery.isLoading,
    isError: catalogueQuery.isError,
    error: catalogueQuery.error,
    retry: () => catalogueQuery.refetch(),
  }
}

interface CategoryEntry {
  category_name: string
  product_ids: number[]
}

/** Return value of {@link usePlanningGridState}. */
export interface PlanningGridState {
  fridges: GridFridge[]
  /** Categories in display order, each with its product_ids in column order. */
  orderedCategories: GridCategory[]
  productIds: Set<number>
  draft: Map<string, number>
  editedKeys: Set<string>
  hasData: boolean
  loadFromGrid: (grid: GridLike) => void
  addProduct: (product: Product) => void
  setCell: (fridgeId: number, productId: number, rawValue: string) => void
  toLines: () => GridLineItem[]
}

/**
 * Owns the editable state of one planning grid. `loadFromGrid` seeds it from a
 * server import/load response; `addProduct` appends a locally-picked product;
 * `setCell` records edits; `toLines` produces the save payload (qty > 0 only,
 * tagging operator-edited cells as `manual`).
 */
export function usePlanningGridState(): PlanningGridState {
  const categoriesQuery = useCategories()

  const [fridges, setFridges] = React.useState<GridFridge[]>([])
  const [categoryEntries, setCategoryEntries] = React.useState<Map<number, CategoryEntry>>(new Map())
  const [draft, setDraft] = React.useState<Map<string, number>>(new Map())
  const [editedKeys, setEditedKeys] = React.useState<Set<string>>(new Set())

  const orderCategory = React.useCallback(
    (categoryId: number) => {
      const ordered = categoriesQuery.data?.ordered ?? []
      const index = ordered.findIndex((category) => category.id === categoryId)
      return index === -1 ? Number.MAX_SAFE_INTEGER : index
    },
    [categoriesQuery.data],
  )

  const loadFromGrid = React.useCallback((grid: GridLike) => {
    setFridges(grid.fridges)
    const entries = new Map<number, CategoryEntry>()
    for (const category of grid.categories) {
      entries.set(category.category_id, {
        category_name: category.category_name,
        product_ids: [...category.product_ids],
      })
    }
    setCategoryEntries(entries)
    const nextDraft = new Map<string, number>()
    for (const cell of grid.cells) nextDraft.set(cellKey(cell.fridge_id, cell.product_id), cell.qty)
    setDraft(nextDraft)
    setEditedKeys(new Set())
  }, [])

  const addProduct = React.useCallback(
    (product: Product) => {
      setCategoryEntries((prev) => {
        const next = new Map(prev)
        const existing = next.get(product.category_id)
        const categoryName =
          categoriesQuery.data?.byId.get(product.category_id) ?? `Category #${product.category_id}`
        if (existing) {
          if (existing.product_ids.includes(product.id)) return prev
          next.set(product.category_id, {
            category_name: existing.category_name,
            product_ids: [...existing.product_ids, product.id],
          })
        } else {
          next.set(product.category_id, {
            category_name: categoryName,
            product_ids: [product.id],
          })
        }
        return next
      })
    },
    [categoriesQuery.data],
  )

  const setCell = React.useCallback((fridgeId: number, productId: number, rawValue: string) => {
    const key = cellKey(fridgeId, productId)
    const parsed = Math.max(0, Math.floor(Number(rawValue) || 0))
    setDraft((prev) => {
      const next = new Map(prev)
      next.set(key, parsed)
      return next
    })
    setEditedKeys((prev) => new Set(prev).add(key))
  }, [])

  const orderedCategories = React.useMemo<GridCategory[]>(() => {
    return Array.from(categoryEntries.entries())
      .map(([categoryId, entry]) => ({
        category_id: categoryId,
        category_name: entry.category_name,
        product_ids: entry.product_ids,
      }))
      .sort((a, b) => orderCategory(a.category_id) - orderCategory(b.category_id))
  }, [categoryEntries, orderCategory])

  const productIds = React.useMemo(() => {
    const ids = new Set<number>()
    for (const entry of categoryEntries.values()) for (const id of entry.product_ids) ids.add(id)
    return ids
  }, [categoryEntries])

  const toLines = React.useCallback((): GridLineItem[] => {
    const lines: GridLineItem[] = []
    for (const [key, qty] of draft.entries()) {
      if (qty <= 0) continue
      const [fridgeId, productId] = key.split(':').map(Number)
      lines.push({
        fridge_id: fridgeId,
        product_id: productId,
        qty,
        source: editedKeys.has(key) ? 'manual' : 'forecast',
      })
    }
    return lines
  }, [draft, editedKeys])

  return {
    fridges,
    orderedCategories,
    productIds,
    draft,
    editedKeys,
    hasData: fridges.length > 0 || categoryEntries.size > 0,
    loadFromGrid,
    addProduct,
    setCell,
    toLines,
  }
}
