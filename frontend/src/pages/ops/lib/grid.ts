/**
 * Shared client-side state for the Excel-like Menu/Dispatch planning grids.
 * Both stages consume the same MenuGridOut/DispatchMatrix shape, so the grid
 * state (fridges, category→product columns, editable quantities, locally-added
 * products) and the product-metadata lookup live here and are reused by both
 * pages - the only differences are the import/save endpoints they call.
 */
import * as React from 'react'
import { sortCategories } from '@/lib/naturalSort'
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

/** Options for {@link PlanningGridState.loadFromGrid}. */
export interface LoadGridOptions {
  /** True when the loaded grid is not saved yet (e.g. an import preview). */
  isUnsaved?: boolean
}

/** Options for {@link PlanningGridState.mergeCategoryFromGrid}. */
export interface MergeCategoryOptions {
  /**
   * True when the grid is the saved state (a save response): the page is then
   * clean unless unsaved changes remain outside the merged category.
   */
  isSavedGrid?: boolean
}

/** Options for {@link PlanningGridState.toLines}. */
export interface ToLinesOptions {
  /**
   * Also emit one qty-0 line for each product that has no quantity yet, so a
   * product added to the grid survives a save and reload.
   */
  keepEmptyProducts?: boolean
}

const EMPTY_GRID: GridLike = {
  fridges: [],
  products: [],
  categories: [],
  cells: [],
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
      // sales_price includes VAT, purchase_price does not: compare like with like.
      const salesExVat = Number(product.sales_price) / (1 + Number(product.vat_rate))
      const marginPct = salesExVat > 0 ? (salesExVat - purchase) / salesExVat : null
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

/** The editable part of a planning grid, held in one state object. */
interface GridContent {
  categoryEntries: Map<number, CategoryEntry>
  draft: Map<string, number>
  editedKeys: Set<string>
  isDirty: boolean
}

const EMPTY_CONTENT: GridContent = {
  categoryEntries: new Map(),
  draft: new Map(),
  editedKeys: new Set(),
  isDirty: false,
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
  /** True after an edit, an added product or an unsaved import, until the next load. */
  isDirty: boolean
  loadFromGrid: (grid: GridLike, options?: LoadGridOptions) => void
  /** Clear every row, column and quantity (e.g. when the week/day key changes). */
  reset: () => void
  /** Merge only one category from an import into the existing grid (Excel
   * "pull one category" flow): other categories' rows/cells are preserved. */
  mergeCategoryFromGrid: (
    grid: GridLike,
    categoryId: number,
    options?: MergeCategoryOptions,
  ) => void
  addProduct: (product: Product) => void
  setCell: (fridgeId: number, productId: number, rawValue: string) => void
  toLines: (options?: ToLinesOptions) => GridLineItem[]
  /** Product ids currently grouped under a category (empty set if none). */
  categoryProductIds: (categoryId: number) => Set<number>
}

/**
 * Owns the editable state of one planning grid. `loadFromGrid` seeds it from a
 * server import/load response; `addProduct` appends a locally-picked product;
 * `setCell` records edits; `toLines` produces the save payload (qty > 0 by default,
 * tagging operator-edited cells as `manual`).
 */
export function usePlanningGridState(): PlanningGridState {
  const categoriesQuery = useCategories()

  const [fridges, setFridges] = React.useState<GridFridge[]>([])
  // One state object so every update (edit, import, save merge) builds on the latest values.
  const [content, setContent] = React.useState<GridContent>(EMPTY_CONTENT)
  const { categoryEntries, draft, editedKeys, isDirty } = content

  const orderCategory = React.useCallback(
    (categoryId: number) => {
      const ordered = sortCategories(categoriesQuery.data?.ordered ?? [])
      const index = ordered.findIndex((category) => category.id === categoryId)
      return index === -1 ? Number.MAX_SAFE_INTEGER : index
    },
    [categoriesQuery.data],
  )

  const loadFromGrid = React.useCallback((grid: GridLike, options: LoadGridOptions = {}) => {
    setFridges(grid.fridges)
    const entries = new Map<number, CategoryEntry>()
    for (const category of grid.categories) {
      entries.set(category.category_id, {
        category_name: category.category_name,
        product_ids: [...category.product_ids],
      })
    }
    const nextDraft = new Map<string, number>()
    for (const cell of grid.cells) nextDraft.set(cellKey(cell.fridge_id, cell.product_id), cell.qty)
    setContent({
      categoryEntries: entries,
      draft: nextDraft,
      editedKeys: new Set(),
      isDirty: options.isUnsaved ?? false,
    })
  }, [])

  const reset = React.useCallback(() => loadFromGrid(EMPTY_GRID), [loadFromGrid])

  const mergeCategoryFromGrid = React.useCallback(
    (grid: GridLike, categoryId: number, options: MergeCategoryOptions = {}) => {
      setFridges((prev) => {
        const seen = new Set(prev.map((fridge) => fridge.fridge_id))
        const merged = [...prev]
        for (const fridge of grid.fridges) {
          if (!seen.has(fridge.fridge_id)) {
            merged.push(fridge)
            seen.add(fridge.fridge_id)
          }
        }
        return merged
      })
      const isSavedGrid = options.isSavedGrid ?? false
      setContent((prev) => mergeCategory(prev, grid, categoryId, isSavedGrid))
    },
    [],
  )

  const addProduct = React.useCallback(
    (product: Product) => {
      const categoryName =
        categoriesQuery.data?.byId.get(product.category_id) ?? `Category #${product.category_id}`
      setContent((prev) => {
        const existing = prev.categoryEntries.get(product.category_id)
        if (existing?.product_ids.includes(product.id)) return prev
        const nextEntries = new Map(prev.categoryEntries)
        nextEntries.set(product.category_id, {
          category_name: existing?.category_name ?? categoryName,
          product_ids: [...(existing?.product_ids ?? []), product.id],
        })
        return { ...prev, categoryEntries: nextEntries, isDirty: true }
      })
    },
    [categoriesQuery.data],
  )

  const setCell = React.useCallback((fridgeId: number, productId: number, rawValue: string) => {
    const key = cellKey(fridgeId, productId)
    const parsed = Math.max(0, Math.floor(Number(rawValue) || 0))
    setContent((prev) => ({
      ...prev,
      draft: new Map(prev.draft).set(key, parsed),
      editedKeys: new Set(prev.editedKeys).add(key),
      isDirty: true,
    }))
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

  const toLines = React.useCallback(
    (options: ToLinesOptions = {}): GridLineItem[] => {
      const lines: GridLineItem[] = []
      const productsWithQuantity = new Set<number>()
      for (const [key, qty] of draft.entries()) {
        if (qty <= 0) continue
        const [fridgeId, productId] = key.split(':').map(Number)
        productsWithQuantity.add(productId)
        lines.push({
          fridge_id: fridgeId,
          product_id: productId,
          qty,
          source: editedKeys.has(key) ? 'manual' : 'forecast',
        })
      }
      const firstFridge = fridges.at(0)
      if (!options.keepEmptyProducts || firstFridge === undefined) return lines

      for (const productId of productIds) {
        if (productsWithQuantity.has(productId)) continue
        lines.push({
          fridge_id: firstFridge.fridge_id,
          product_id: productId,
          qty: 0,
          source: 'manual',
        })
      }
      return lines
    },
    [draft, editedKeys, fridges, productIds],
  )

  const categoryProductIds = React.useCallback(
    (categoryId: number) => new Set(categoryEntries.get(categoryId)?.product_ids ?? []),
    [categoryEntries],
  )

  return {
    fridges,
    orderedCategories,
    productIds,
    draft,
    editedKeys,
    hasData: fridges.length > 0 || categoryEntries.size > 0,
    isDirty,
    loadFromGrid,
    reset,
    mergeCategoryFromGrid,
    addProduct,
    setCell,
    toLines,
    categoryProductIds,
  }
}


/**
 * Replaces one category's columns and cells in `current` with those from `grid`,
 * keeping every other category untouched. After a save (`isSavedGrid`) the result
 * is clean only when no edits remain and it equals the saved grid.
 */
function mergeCategory(
  current: GridContent,
  grid: GridLike,
  categoryId: number,
  isSavedGrid: boolean,
): GridContent {
  const imported = grid.categories.find((category) => category.category_id === categoryId)
  const importedProductIds = new Set(imported?.product_ids ?? [])

  const categoryEntries = new Map(current.categoryEntries)
  if (imported) {
    categoryEntries.set(categoryId, {
      category_name: imported.category_name,
      product_ids: [...imported.product_ids],
    })
  } else {
    categoryEntries.delete(categoryId) // category has no imported rows -> clear it
  }

  // Products that were (or now are) in this category, so their old cells go.
  const staleProductIds = new Set<number>(importedProductIds)
  const previousProductIds = current.categoryEntries.get(categoryId)?.product_ids ?? []
  for (const productId of previousProductIds) staleProductIds.add(productId)

  const draft = new Map(current.draft)
  for (const key of draft.keys()) {
    if (staleProductIds.has(productIdOfKey(key))) draft.delete(key)
  }
  // A save response carries every category; only this category's cells may replace the draft.
  const categoryCells = grid.cells.filter((cell) => importedProductIds.has(cell.product_id))
  for (const cell of categoryCells) {
    draft.set(cellKey(cell.fridge_id, cell.product_id), cell.qty)
  }

  const editedKeys = new Set(current.editedKeys)
  for (const key of editedKeys) {
    if (staleProductIds.has(productIdOfKey(key))) editedKeys.delete(key)
  }

  const isClean =
    isSavedGrid && editedKeys.size === 0 && gridMatches(categoryEntries, draft, grid)
  return {
    categoryEntries,
    draft,
    editedKeys,
    isDirty: !isClean,
  }
}

function productIdOfKey(key: string): number {
  return Number(key.split(':')[1])
}

/** True when the grid's products and quantities equal `grid` (a missing cell counts as 0). */
function gridMatches(
  entries: Map<number, CategoryEntry>,
  draft: Map<string, number>,
  grid: GridLike,
): boolean {
  const gridProductIds = new Set<number>()
  for (const category of grid.categories) {
    for (const productId of category.product_ids) gridProductIds.add(productId)
  }
  const shownProductIds = new Set<number>()
  for (const entry of entries.values()) {
    for (const productId of entry.product_ids) shownProductIds.add(productId)
  }
  if (gridProductIds.size !== shownProductIds.size) return false
  for (const productId of shownProductIds) {
    if (!gridProductIds.has(productId)) return false
  }

  const gridQtyByKey = new Map<string, number>()
  for (const cell of grid.cells) {
    gridQtyByKey.set(cellKey(cell.fridge_id, cell.product_id), cell.qty)
  }
  for (const [key, qty] of draft) {
    if (qty !== (gridQtyByKey.get(key) ?? 0)) return false
  }
  for (const [key, qty] of gridQtyByKey) {
    if (qty !== (draft.get(key) ?? 0)) return false
  }
  return true
}
