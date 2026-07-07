import * as React from 'react'
import { useMutation } from '@tanstack/react-query'
import { Download, LayoutGrid, Plus, Save, Sparkles } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
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
import {
  useCategories,
  useMenuCategoryColumns,
  useProductCatalogue,
  useSupplierMap,
} from '@/pages/ops/lib/reference'
import { usePlanningGridState, useProductMeta } from '@/pages/ops/lib/grid'
import { useWeekDayKey, weekKeyLabel } from '@/pages/ops/lib/pipelineKey'
import type { MenuGrid, PurchaseOrder } from '@/pages/ops/lib/types'

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
  const [draftPoSupplierId, setDraftPoSupplierId] = React.useState<number | null>(null)

  // Any stage change clears the current grid — it belongs to another key.
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
        params: { year: key.year, week: key.week, day_name: key.dayName },
      }),
    onSuccess: (result) => {
      grid.loadFromGrid(result)
      setLoaded(true)
      toast.success(
        result.products.length
          ? `Imported ${result.products.length} products from the saved forecast`
          : 'Imported from forecast — no allocations yet. Add products to build the menu.',
      )
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved forecast for this key — save a forecast first.')
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

  const saveMutation = useMutation({
    mutationFn: (overwrite: boolean) =>
      api.post<MenuGrid>('/api/v1/menus/save', {
        year: key.year,
        week: key.week,
        day_name: key.dayName,
        lines: grid.toLines().map(({ fridge_id, product_id, qty }) => ({ fridge_id, product_id, qty })),
        overwrite,
      }),
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

  const draftPoMutation = useMutation({
    mutationFn: (supplierId: number) =>
      api.post<PurchaseOrder>('/api/v1/menus/draft-purchase-orders', undefined, {
        params: { year: key.year, week: key.week, day_name: key.dayName, supplier_id: supplierId },
      }),
    onSuccess: (order) => {
      toast.success(`Draft PO ${order.order_no} created`, {
        description: `Total ${order.total_incl_vat} incl. VAT · status ${order.status}`,
      })
      setDraftPoSupplierId(null)
    },
    onError: (error) => {
      setDraftPoSupplierId(null)
      toast.error(error instanceof ApiError ? error.message : 'Failed to draft purchase order')
    },
  })

  function handleDraftPo(supplierId: number) {
    setDraftPoSupplierId(supplierId)
    draftPoMutation.mutate(supplierId)
  }

  const isBusy = importMutation.isPending || loadSavedMutation.isPending
  const canSave = grid.fridges.length > 0 && grid.productIds.size > 0

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="Planning / Menu"
        title="Menu"
        description="Build the week/day assortment: import from the saved forecast or a previous menu, add products, edit per-fridge quantities, then save."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => setAddOpen(true)} disabled={!catalogueQuery.data}>
              <Plus className="h-4 w-4" />
              Add product
            </Button>
            <Button
              variant="outline"
              onClick={() => importMutation.mutate()}
              disabled={importMutation.isPending}
            >
              <Sparkles className="h-4 w-4" />
              {importMutation.isPending ? 'Importing…' : 'Import from Forecast'}
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
        }
      />

      <WeekDayPicker value={key} onChange={setKey} />

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
          onDraftPo={handleDraftPo}
          draftPoPendingSupplierId={draftPoSupplierId}
        />
      )}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add a product"
        description="Filter the catalogue by category, then supplier, then pick a product to add a column to the grid."
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
