import * as React from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, LayoutGrid, Plus, Save } from 'lucide-react'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/sonner'
import { api, ApiError } from '@/lib/api'
import { WeekDayPicker } from '@/pages/ops/components/WeekDayPicker'
import { ConfirmDialog } from '@/pages/ops/components/ConfirmDialog'
import { Modal } from '@/pages/ops/components/Modal'
import { PlanningGrid } from '@/pages/ops/components/PlanningGrid'
import { AddProductPicker } from '@/pages/ops/components/AddProductPicker'
import { CategoryScopeSelect } from '@/pages/ops/components/CategoryScopeSelect'
import {
  useCategories,
  useMenuCategoryColumns,
  useProductCatalogue,
  useSupplierMap,
} from '@/pages/ops/lib/reference'
import { usePlanningGridState, useProductMeta } from '@/pages/ops/lib/grid'
import { useWeekDayKey, weekKeyLabel } from '@/pages/ops/lib/pipelineKey'
import type { MenuGrid } from '@/pages/ops/lib/types'

export function MenuPage() {
  const { key, setKey } = useWeekDayKey()
  const grid = usePlanningGridState()
  const { meta: productMeta, isLoading: metaLoading } = useProductMeta()

  const categoriesQuery = useCategories()
  const supplierMapQuery = useSupplierMap()
  const catalogueQuery = useProductCatalogue()
  const columnsQuery = useMenuCategoryColumns()

  const [loaded, setLoaded] = React.useState(false)
  const [overwriteOpen, setOverwriteOpen] = React.useState(false)
  const [addOpen, setAddOpen] = React.useState(false)
  // null = whole menu; a category id scopes pull/save to that one category.
  const [scopeCategoryId, setScopeCategoryId] = React.useState<number | null>(null)

  // Any stage change clears the current grid - it belongs to another key.
  React.useEffect(() => {
    setLoaded(false)
  }, [key.year, key.week, key.dayName])

  const categoryName = React.useCallback(
    (id: number) => categoriesQuery.data?.byId.get(id) ?? `Category #${id}`,
    [categoriesQuery.data],
  )
  const supplierName = React.useCallback(
    (id: number) => supplierMapQuery.data?.get(id) ?? `Supplier #${id}`,
    [supplierMapQuery.data],
  )

  const importMutation = useMutation({
    mutationFn: () =>
      api.post<MenuGrid>('/api/v1/menus/import-from-forecast', undefined, {
        params: {
          year: key.year,
          week: key.week,
          day_name: key.dayName,
          ...(scopeCategoryId !== null ? { category_id: scopeCategoryId } : {}),
        },
      }),
    onSuccess: (result) => {
      if (scopeCategoryId !== null) {
        grid.mergeCategoryFromGrid(result, scopeCategoryId)
      } else {
        grid.loadFromGrid(result)
      }
      setLoaded(true)
      toast.success(
        result.products.length
          ? `Imported ${result.products.length} products from the saved forecast`
          : 'Imported from forecast - no allocations yet. Add products to build the menu.',
      )
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved forecast for this key - save a forecast first.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to import from forecast')
      }
    },
  })

  const loadSavedMutation = useMutation({
    mutationFn: () =>
      api.get<MenuGrid>('/api/v1/menus/saved', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
      }),
    onSuccess: (result) => {
      grid.loadFromGrid(result)
      setLoaded(true)
      toast.success(`Loaded saved menu for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved menu for this key yet.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to load saved menu')
      }
    },
  })

  // Auto-load the saved menu for the selected date if one exists (silent when
  // none). Fires whenever the week/day key changes; never overrides live edits.
  const savedMenuQuery = useQuery({
    queryKey: ['ops', 'menu', 'saved', key.year, key.week, key.dayName],
    queryFn: ({ signal }) =>
      api.get<MenuGrid>('/api/v1/menus/saved', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
        signal,
      }),
    retry: false,
  })

  React.useEffect(() => {
    const saved = savedMenuQuery.data
    if (
      saved &&
      saved.year === key.year &&
      saved.week === key.week &&
      saved.day_name === key.dayName &&
      !loaded
    ) {
      grid.loadFromGrid(saved)
      setLoaded(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedMenuQuery.data, loaded, key.year, key.week, key.dayName])

  const saveMutation = useMutation({
    mutationFn: (overwrite: boolean) => {
      const scopedProductIds =
        scopeCategoryId !== null ? grid.categoryProductIds(scopeCategoryId) : null
      const lines = grid
        .toLines()
        .filter(({ product_id }) => scopedProductIds === null || scopedProductIds.has(product_id))
        .map(({ fridge_id, product_id, qty }) => ({ fridge_id, product_id, qty }))
      return api.post<MenuGrid>('/api/v1/menus/save', {
        year: key.year,
        week: key.week,
        day_name: key.dayName,
        lines,
        overwrite,
        ...(scopeCategoryId !== null ? { category_id: scopeCategoryId } : {}),
      })
    },
    onSuccess: (result) => {
      grid.loadFromGrid(result)
      setLoaded(true)
      setOverwriteOpen(false)
      toast.success(`Menu saved for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'exists') {
        setOverwriteOpen(true)
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to save menu')
    },
  })

  const isBusy = importMutation.isPending || loadSavedMutation.isPending
  const canSave = grid.fridges.length > 0 && grid.productIds.size > 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <WeekDayPicker value={key} onChange={setKey} />
        <div className="flex flex-wrap items-center gap-2">
          <CategoryScopeSelect value={scopeCategoryId} onChange={setScopeCategoryId} />
          <Button variant="outline" onClick={() => setAddOpen(true)} disabled={!catalogueQuery.data}>
            <Plus className="h-4 w-4" />
            Product
          </Button>
          <Button
            variant="outline"
            onClick={() => importMutation.mutate()}
            disabled={importMutation.isPending}
          >
            <Download className="h-4 w-4" />
            {importMutation.isPending ? 'Importing…' : 'From Forecast'}
          </Button>
          <Button
            variant="outline"
            onClick={() => loadSavedMutation.mutate()}
            disabled={loadSavedMutation.isPending}
          >
            <Download className="h-4 w-4" />
            {loadSavedMutation.isPending ? 'Loading…' : 'Load saved'}
          </Button>
          <Button onClick={() => saveMutation.mutate(false)} disabled={saveMutation.isPending || !canSave}>
            <Save className="h-4 w-4" />
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>

      {catalogueQuery.isError ? (
        <ErrorState
          title="Failed to load the product catalogue"
          error={catalogueQuery.error}
          onRetry={() => catalogueQuery.refetch()}
        />
      ) : isBusy || (loaded && metaLoading) ? (
        <LoadingSkeleton rows={8} columns={8} />
      ) : !loaded || !grid.hasData ? (
        <EmptyState
          icon={<LayoutGrid className="h-8 w-8" />}
          title="No menu loaded"
          description="Import from the saved forecast, load a previously saved menu, or add products to start building this week's menu."
        />
      ) : (
        <PlanningGrid
          fridges={grid.fridges}
          categories={grid.orderedCategories}
          productMeta={productMeta}
          draft={grid.draft}
          onCellChange={grid.setCell}
          editedKeys={grid.editedKeys}
          columnsPerCategory={columnsQuery.data ?? 6}
        />
      )}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add a product"
        className="max-w-lg"
        footer={
          <Button variant="outline" onClick={() => setAddOpen(false)}>
            Done
          </Button>
        }
      >
        {catalogueQuery.data ? (
          <AddProductPicker
            products={catalogueQuery.data.items}
            categoryName={categoryName}
            supplierName={supplierName}
            existingProductIds={grid.productIds}
            onAdd={(product) => {
              grid.addProduct(product)
              setLoaded(true)
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
        onConfirm={() => saveMutation.mutate(true)}
        title="Overwrite the saved menu?"
        description={`A saved menu already exists for ${weekKeyLabel(key)}. Overwriting replaces its lines with the current grid.`}
        confirmLabel="Overwrite"
        destructive
        pending={saveMutation.isPending}
      />
    </div>
  )
}

export default MenuPage
