import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, LayoutGrid, Plus, Save } from 'lucide-react'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Modal } from '@/components/shared/Modal'
import { Toolbar } from '@/components/shared/Toolbar'
import { UnsavedChangesDialog } from '@/components/shared/UnsavedChangesDialog'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/sonner'
import { useUnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard'
import { api, ApiError } from '@/lib/api'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { AddProductPicker } from '@/pages/ops/components/AddProductPicker'
import { CategoryScopeSelect } from '@/pages/ops/components/CategoryScopeSelect'
import { PlanningGrid, type PlanningGridDetailRow } from '@/pages/ops/components/PlanningGrid'
import { WeekDayPicker } from '@/pages/ops/components/WeekDayPicker'
import { usePlanningGridState, useProductMeta } from '@/pages/ops/lib/grid'
import { useWeekDayKey, weekKeyLabel, type WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import {
  useCategoryName,
  useProductCatalogue,
  useSupplierMap,
} from '@/pages/ops/lib/reference'
import type { MenuGrid } from '@/pages/ops/lib/types'
import { MenuSummary } from '@/pages/ops/menu/MenuSummary'
import {
  menuKeyParams,
  SAVED_MENU_QUERY_KEY,
  useMenuForKey,
  useMenuStockBalances,
} from '@/pages/ops/menu/menuApi'
import { computeMenuTotals } from '@/pages/ops/menu/menuTotals'

const NOT_FOUND_STATUS = 404
const EXISTS_ERROR_CODE = 'exists'
const NO_FRIDGES_HINT =
  'Set delivery days on the fridges, import from the saved forecast, ' +
  'or add products to start this menu.'

function keyId(key: WeekDayKey): string {
  return `${key.year}-${key.week}-${key.dayName}`
}

export function MenuPage() {
  const { key, setKey } = useWeekDayKey()
  const grid = usePlanningGridState()
  const guard = useUnsavedChangesGuard(grid.isDirty)
  const queryClient = useQueryClient()
  const { meta: productMeta, isLoading: metaLoading } = useProductMeta()

  const supplierMapQuery = useSupplierMap()
  const catalogueQuery = useProductCatalogue()
  const stockQuery = useMenuStockBalances()
  const keyMenuQuery = useMenuForKey(key)

  // The key whose menu the grid currently holds; null while the next key loads.
  const [loadedKeyId, setLoadedKeyId] = React.useState<string | null>(null)
  const [overwriteOpen, setOverwriteOpen] = React.useState(false)
  const [addOpen, setAddOpen] = React.useState(false)
  // null = whole menu; a category id scopes pull/save to that one category.
  const [scopeCategoryId, setScopeCategoryId] = React.useState<number | null>(null)

  const scopeCategoryName = useCategoryName(scopeCategoryId)
  const currentKeyId = keyId(key)
  const isKeyLoaded = loadedKeyId === currentKeyId

  const { loadFromGrid } = grid
  React.useEffect(() => {
    if (isKeyLoaded || keyMenuQuery.isFetching || !keyMenuQuery.data) return
    loadFromGrid(keyMenuQuery.data)
    setLoadedKeyId(currentKeyId)
  }, [isKeyLoaded, keyMenuQuery.isFetching, keyMenuQuery.data, currentKeyId, loadFromGrid])

  const supplierName = React.useCallback(
    (id: number) => supplierMapQuery.data?.get(id) ?? `Supplier #${id}`,
    [supplierMapQuery.data],
  )

  const importMutation = useMutation({
    mutationFn: () =>
      api.post<MenuGrid>('/api/v1/menus/import-from-forecast', undefined, {
        params: {
          ...menuKeyParams(key),
          ...(scopeCategoryId !== null ? { category_id: scopeCategoryId } : {}),
        },
      }),
    onSuccess: (result) => {
      if (scopeCategoryId !== null) {
        grid.mergeCategoryFromGrid(result, scopeCategoryId)
      } else {
        grid.loadFromGrid(result, { isUnsaved: true })
      }
      toast.success(
        result.products.length
          ? `Imported ${result.products.length} products from the saved forecast`
          : 'Imported from forecast - no allocations yet. Add products to build the menu.',
      )
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === NOT_FOUND_STATUS) {
        toast.error('No saved forecast for this key - save a forecast first.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to import from forecast')
      }
    },
  })

  const loadSavedMutation = useMutation({
    mutationFn: () =>
      api.get<MenuGrid>('/api/v1/menus/saved', { params: menuKeyParams(key) }),
    onSuccess: (result) => {
      grid.loadFromGrid(result)
      toast.success(`Loaded saved menu for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === NOT_FOUND_STATUS) {
        toast.error('No saved menu for this key yet.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to load saved menu')
      }
    },
  })

  const saveMutation = useMutation({
    mutationFn: (overwrite: boolean) => {
      const scopedProductIds =
        scopeCategoryId !== null ? grid.categoryProductIds(scopeCategoryId) : null
      const lines = grid
        .toLines({ keepEmptyProducts: true })
        .filter(({ product_id }) => scopedProductIds === null || scopedProductIds.has(product_id))
        .map(({ fridge_id, product_id, qty }) => ({ fridge_id, product_id, qty }))
      return api.post<MenuGrid>('/api/v1/menus/save', {
        ...menuKeyParams(key),
        lines,
        overwrite,
        ...(scopeCategoryId !== null ? { category_id: scopeCategoryId } : {}),
      })
    },
    onSuccess: (result) => {
      // A category-scoped save keeps the other categories' unsaved edits on screen.
      if (scopeCategoryId !== null) {
        grid.mergeCategoryFromGrid(result, scopeCategoryId, { isSavedGrid: true })
      } else {
        grid.loadFromGrid(result)
      }
      void queryClient.invalidateQueries({ queryKey: SAVED_MENU_QUERY_KEY })
      toast.success(`Menu saved for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === EXISTS_ERROR_CODE) {
        setOverwriteOpen(true)
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to save menu')
    },
  })

  function handleConfirmOverwrite() {
    // Closing first keeps a double click on Overwrite from sending two saves.
    setOverwriteOpen(false)
    saveMutation.mutate(true)
  }

  function handleKeyChange(nextKey: WeekDayKey) {
    guard.confirmDiscard(() => {
      grid.reset()
      setLoadedKeyId(null)
      setKey(nextKey)
    })
  }

  const gridLines = grid.toLines()
  const menuTotals = computeMenuTotals(gridLines, catalogueQuery.data?.byId ?? new Map())
  const stockDetailRows: PlanningGridDetailRow[] = [
    {
      label: 'In stock',
      render: (productId) => stockQuery.data?.get(productId)?.in_stock_qty ?? EMPTY_PLACEHOLDER,
    },
    {
      label: 'On order',
      render: (productId) => stockQuery.data?.get(productId)?.on_order_qty ?? EMPTY_PLACEHOLDER,
    },
  ]

  const isBusy = importMutation.isPending || loadSavedMutation.isPending
  const isLoadingGrid = isBusy || !isKeyLoaded || metaLoading
  const canSave = grid.fridges.length > 0 && grid.productIds.size > 0

  function renderGridArea() {
    if (catalogueQuery.isError) {
      return (
        <ErrorState
          title="Failed to load the product catalogue"
          error={catalogueQuery.error}
          onRetry={() => catalogueQuery.refetch()}
        />
      )
    }
    if (keyMenuQuery.isError) {
      return (
        <ErrorState
          title="Failed to load the menu for this day"
          error={keyMenuQuery.error}
          onRetry={() => keyMenuQuery.refetch()}
        />
      )
    }
    if (isLoadingGrid) return <LoadingSkeleton rows={8} columns={8} />
    if (!grid.hasData) {
      return (
        <EmptyState
          icon={<LayoutGrid className="h-8 w-8" />}
          title="No fridge is delivered on this day"
          description={NO_FRIDGES_HINT}
        />
      )
    }
    return (
      <>
        <MenuSummary totals={menuTotals} />
        <PlanningGrid
          fridges={grid.fridges}
          categories={grid.orderedCategories}
          productMeta={productMeta}
          draft={grid.draft}
          onCellChange={grid.setCell}
          editedKeys={grid.editedKeys}
          extraDetailRows={stockDetailRows}
        />
      </>
    )
  }

  return (
    <div className="space-y-4">
      <Toolbar
        left={
          <>
            <WeekDayPicker
              value={key}
              onChange={handleKeyChange}
              compact
            />
            <CategoryScopeSelect
              value={scopeCategoryId}
              onChange={setScopeCategoryId}
            />
          </>
        }
        right={
          <>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => setAddOpen(true)}
              disabled={!catalogueQuery.data || !isKeyLoaded}
            >
              <Plus className="h-4 w-4" />
              Product
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => guard.confirmDiscard(() => importMutation.mutate())}
              disabled={importMutation.isPending || !isKeyLoaded}
            >
              <Download className="h-4 w-4" />
              {importMutation.isPending ? 'Importing…' : 'From Forecast'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => guard.confirmDiscard(() => loadSavedMutation.mutate())}
              disabled={loadSavedMutation.isPending || !isKeyLoaded}
            >
              <Download className="h-4 w-4" />
              {loadSavedMutation.isPending ? 'Loading…' : 'Load saved'}
            </Button>
            <Button
              size="sm"
              className="h-9"
              onClick={() => saveMutation.mutate(false)}
              disabled={saveMutation.isPending || !canSave}
            >
              <Save className="h-4 w-4" />
              {saveMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          </>
        }
      />

      {renderGridArea()}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add a product"
        className="max-w-lg"
        footer={
          <Button
            variant="outline"
            onClick={() => setAddOpen(false)}
          >
            Done
          </Button>
        }
      >
        {catalogueQuery.data ? (
          <AddProductPicker
            products={catalogueQuery.data.items}
            supplierName={supplierName}
            existingProductIds={grid.productIds}
            onAdd={(product) => {
              grid.addProduct(product)
              toast.success(`${product.name} added`)
            }}
          />
        ) : (
          <LoadingSkeleton rows={3} columns={2} />
        )}
      </Modal>

      <ConfirmDialog
        open={overwriteOpen}
        onClose={() => setOverwriteOpen(false)}
        onConfirm={handleConfirmOverwrite}
        title="Overwrite the saved menu?"
        description={describeMenuOverwrite(weekKeyLabel(key), scopeCategoryName)}
        confirmLabel="Overwrite"
        destructive
      />

      <UnsavedChangesDialog guard={guard} />
    </div>
  )
}

export default MenuPage

function describeMenuOverwrite(keyLabel: string, scopeCategoryName: string | null): string {
  const existing = `A saved menu already exists for ${keyLabel}. `
  if (scopeCategoryName === null) {
    return existing + 'Overwriting replaces its lines with the current grid.'
  }
  return (
    existing +
    `Overwriting replaces only its ${scopeCategoryName} lines with the current grid; ` +
    'the other categories stay as saved.'
  )
}
