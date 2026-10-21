import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileSpreadsheet, FolderOpen, Import, Save, Truck } from 'lucide-react'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { StatusChip } from '@/components/shared/StatusChip'
import { Toolbar } from '@/components/shared/Toolbar'
import { UnsavedChangesDialog } from '@/components/shared/UnsavedChangesDialog'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/sonner'
import { useUnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard'
import { api, ApiError } from '@/lib/api'
import { formatEuro } from '@/lib/format'
import { CategoryScopeSelect } from '@/pages/ops/components/CategoryScopeSelect'
import { PlanningGrid, type ProductMeta } from '@/pages/ops/components/PlanningGrid'
import { WeekDayPicker } from '@/pages/ops/components/WeekDayPicker'
import { DispatchSummary, type DispatchTotals } from '@/pages/ops/dispatch/DispatchSummary'
import {
  DISPATCH_QUERY_KEY,
  downloadDispatchExcel,
  fetchSavedDispatch,
  quantitiesSignature,
  type SavedDispatch,
} from '@/pages/ops/dispatch/dispatchApi'
import { usePlanningGridState, useProductMeta, type GridLike } from '@/pages/ops/lib/grid'
import { keyIsPast, useWeekDayKey, weekKeyLabel } from '@/pages/ops/lib/pipelineKey'
import type { WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import {
  useCategoryName,
  useMenuCategoryColumns,
  useProductCatalogue,
} from '@/pages/ops/lib/reference'
import type {
  ConfirmResult,
  DispatchRead,
  DispatchMatrix,
  StockBlockedEntry,
} from '@/pages/ops/lib/types'

const EMPTY_GRID: GridLike = { fridges: [], products: [], categories: [], cells: [] }
const DEFAULT_COLUMNS_PER_CATEGORY = 6
const STOCK_BLOCKED_PREVIEW_COUNT = 6

export function DispatchPage() {
  const queryClient = useQueryClient()
  const { key, setKey } = useWeekDayKey()
  const grid = usePlanningGridState()
  const { meta: productMeta, isLoading: metaLoading } = useProductMeta()

  const catalogueQuery = useProductCatalogue()
  const columnsQuery = useMenuCategoryColumns()

  const [loaded, setLoaded] = React.useState(false)
  const [savedDispatch, setSavedDispatch] = React.useState<DispatchRead | null>(null)
  const [dispatchedCostTotal, setDispatchedCostTotal] = React.useState<string | null>(null)
  const [savedQuantities, setSavedQuantities] = React.useState('')
  const [overwriteOpen, setOverwriteOpen] = React.useState(false)
  const [createOpen, setCreateOpen] = React.useState(false)
  const [force, setForce] = React.useState(false)
  // null = whole dispatch; a category id scopes pull/save to that one category.
  const [scopeCategoryId, setScopeCategoryId] = React.useState<number | null>(null)

  const scopeCategoryName = useCategoryName(scopeCategoryId)
  const isPast = keyIsPast(key)
  const dispatchLines = grid.toLines()
  const isDirty = loaded && quantitiesSignature(dispatchLines) !== savedQuantities
  const guard = useUnsavedChangesGuard(isDirty)
  const status = savedDispatch?.status ?? null
  const isDispatched = status === 'dispatched' || status === 'reconciled'

  const { loadFromGrid } = grid

  const rememberSavedState = React.useCallback(({ saved, matrix }: SavedDispatch) => {
    setSavedDispatch(saved)
    setSavedQuantities(quantitiesSignature(matrix.cells))
    setDispatchedCostTotal(matrix.dispatched_cost_total)
  }, [])

  const showSavedDispatch = React.useCallback(
    (savedDispatchWithMatrix: SavedDispatch) => {
      loadFromGrid(savedDispatchWithMatrix.matrix)
      rememberSavedState(savedDispatchWithMatrix)
      setLoaded(true)
    },
    [loadFromGrid, rememberSavedState],
  )

  function changeKey(nextKey: WeekDayKey) {
    guard.confirmDiscard(() => setKey(nextKey))
  }

  React.useEffect(() => {
    loadFromGrid(EMPTY_GRID)
    setLoaded(false)
    setSavedDispatch(null)
    setSavedQuantities('')
    setDispatchedCostTotal(null)
    setForce(false)
  }, [key.year, key.week, key.dayName, loadFromGrid])

  // Silent when the key has no saved dispatch yet (404).
  const savedDispatchQuery = useQuery({
    queryKey: [...DISPATCH_QUERY_KEY, 'saved', key.year, key.week, key.dayName],
    queryFn: ({ signal }) => fetchSavedDispatch(key, signal),
    retry: false,
  })

  React.useEffect(() => {
    if (savedDispatchQuery.data && !savedDispatchQuery.isFetching && !loaded) {
      showSavedDispatch(savedDispatchQuery.data)
    }
  }, [savedDispatchQuery.data, savedDispatchQuery.isFetching, loaded, showSavedDispatch])

  const importMutation = useMutation({
    mutationFn: () =>
      api.post<DispatchMatrix>('/api/v1/dispatches/import-from-menu', undefined, {
        params: {
          year: key.year,
          week: key.week,
          day_name: key.dayName,
          ...(scopeCategoryId !== null ? { category_id: scopeCategoryId } : {}),
        },
      }),
    onSuccess: (matrix) => {
      if (scopeCategoryId !== null) {
        grid.mergeCategoryFromGrid(matrix, scopeCategoryId)
      } else {
        grid.loadFromGrid(matrix)
      }
      setLoaded(true)
      toast.success(`Imported ${matrix.products.length} products from the saved menu`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved menu for this key - save a menu first.')
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to import from menu')
    },
  })

  const loadSavedMutation = useMutation({
    mutationFn: () => fetchSavedDispatch(key),
    onSuccess: (savedDispatchWithMatrix) => {
      showSavedDispatch(savedDispatchWithMatrix)
      toast.success(
        `Loaded saved dispatch for ${weekKeyLabel(key)} (${savedDispatchWithMatrix.saved.status})`,
      )
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved dispatch for this key yet.')
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to load saved dispatch')
    },
  })

  const downloadMutation = useMutation({
    mutationFn: downloadDispatchExcel,
    onError: (error) => toast.error(error.message),
  })

  const saveMutation = useMutation({
    mutationFn: async (overwrite: boolean) => {
      const scopedProductIds =
        scopeCategoryId !== null ? grid.categoryProductIds(scopeCategoryId) : null
      const lines = dispatchLines.filter(
        (line) => scopedProductIds === null || scopedProductIds.has(line.product_id),
      )
      await api.post<DispatchRead>('/api/v1/dispatches/save', {
        year: key.year,
        week: key.week,
        day_name: key.dayName,
        lines,
        overwrite,
        ...(scopeCategoryId !== null ? { category_id: scopeCategoryId } : {}),
      })
      // A category-scoped save keeps the other saved categories, so re-read what is stored.
      return fetchSavedDispatch(key)
    },
    onSuccess: (savedDispatchWithMatrix) => {
      rememberSavedState(savedDispatchWithMatrix)
      setOverwriteOpen(false)
      queryClient.invalidateQueries({ queryKey: DISPATCH_QUERY_KEY })
      toast.success('Dispatch saved as planned', {
        description: 'Stock is NOT reduced by saving - only "Create dispatch" moves stock.',
      })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'exists') {
        setOverwriteOpen(true)
        return
      }
      if (error instanceof ApiError && error.code === 'conflict') {
        toast.error('This dispatch is already dispatched and can no longer be edited.')
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to save dispatch')
    },
  })

  const createMutation = useMutation({
    mutationFn: async (forceCreate: boolean) => {
      const result = await api.post<ConfirmResult>(
        '/api/v1/dispatches/create-individual',
        undefined,
        {
          params: {
            year: key.year,
            week: key.week,
            day_name: key.dayName,
            force: forceCreate,
          },
        },
      )
      const dispatched = await fetchSavedDispatch(key)
      return { result, dispatched }
    },
    onSuccess: ({ result, dispatched }) => {
      showSavedDispatch(dispatched)
      setCreateOpen(false)
      queryClient.invalidateQueries({ queryKey: DISPATCH_QUERY_KEY })
      toast.success(`Dispatch created: ${result.movements_created} stock movements`, {
        description: 'Stock is reduced for every dispatched product. Excel file downloading.',
      })
      downloadMutation.mutate(dispatched.saved)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'stock_blocked') {
        toast.error('Stock blocked - dispatch not created', {
          description: describeStockBlocked(error, productMeta),
        })
        return
      }
      if (error instanceof ApiError && error.code === 'past_date_requires_force') {
        toast.error('This delivery date is in the past - tick "force" to dispatch it anyway.')
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to create dispatch')
    },
  })

  const isAutoLoading = savedDispatchQuery.isFetching && !loaded
  const isBusy = importMutation.isPending || loadSavedMutation.isPending || isAutoLoading
  const canSave = grid.fridges.length > 0 && grid.productIds.size > 0 && !isDispatched
  const createBlocker = describeCreateBlocker(savedDispatch, isDirty)

  const catalogueCostEuros = dispatchLines.reduce((sum, line) => {
    const purchasePrice = Number(productMeta(line.product_id)?.purchasePrice ?? 0)
    return sum + line.qty * purchasePrice
  }, 0)
  const isSnapshotCost = isDispatched && dispatchedCostTotal !== null
  const totals: DispatchTotals = {
    fridgeCount: grid.fridges.length,
    fridgesToDispatch: new Set(dispatchLines.map((line) => line.fridge_id)).size,
    totalUnits: dispatchLines.reduce((sum, line) => sum + line.qty, 0),
    totalCostEuros: isSnapshotCost ? Number(dispatchedCostTotal) : catalogueCostEuros,
  }

  return (
    <div className="space-y-6">
      <Toolbar
        left={
          <>
            <WeekDayPicker value={key} onChange={changeKey} compact />
            <CategoryScopeSelect value={scopeCategoryId} onChange={setScopeCategoryId} />
            {status ? <StatusChip status={status} /> : null}
            {isPast ? <StatusChip variant="warning" label="Past date" /> : null}
          </>
        }
        right={
          <>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              title={
                isDispatched
                  ? 'This day is already dispatched.'
                  : 'Import the planned quantities from the saved menu'
              }
              onClick={() => guard.confirmDiscard(() => importMutation.mutate())}
              disabled={importMutation.isPending || isDispatched}
            >
              <Import className="h-4 w-4" />
              {importMutation.isPending ? 'Importing…' : 'From Menu'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              title="Reload the saved dispatch for this day"
              onClick={() => guard.confirmDiscard(() => loadSavedMutation.mutate())}
              disabled={loadSavedMutation.isPending}
            >
              <FolderOpen className="h-4 w-4" />
              {loadSavedMutation.isPending ? 'Loading…' : 'Load saved'}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              className="h-9"
              onClick={() => saveMutation.mutate(false)}
              disabled={saveMutation.isPending || !canSave}
            >
              <Save className="h-4 w-4" />
              {saveMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
            {isDispatched && savedDispatch ? (
              <Button
                size="sm"
                className="h-9"
                onClick={() => downloadMutation.mutate(savedDispatch)}
                disabled={downloadMutation.isPending}
              >
                <FileSpreadsheet className="h-4 w-4" />
                {downloadMutation.isPending ? 'Downloading…' : 'Download Excel'}
              </Button>
            ) : (
              <span title={createBlocker ?? 'Create Individual Dispatch for this day'}>
                <Button
                  size="sm"
                  className="h-9"
                  onClick={() => {
                    setForce(false)
                    setCreateOpen(true)
                  }}
                  disabled={createMutation.isPending || createBlocker !== null}
                >
                  <Truck className="h-4 w-4" />
                  Create dispatch
                </Button>
              </span>
            )}
          </>
        }
      />

      {loaded && grid.hasData ? (
        <DispatchSummary totals={totals} isSnapshotCost={isSnapshotCost} />
      ) : null}

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
          icon={<Truck className="h-8 w-8" />}
          title="No dispatch loaded"
          description="Import from the saved menu or load a previously saved dispatch to edit the fridge × product grid."
        />
      ) : (
        <PlanningGrid
          fridges={grid.fridges}
          categories={grid.orderedCategories}
          productMeta={productMeta}
          draft={grid.draft}
          onCellChange={grid.setCell}
          editedKeys={grid.editedKeys}
          columnsPerCategory={columnsQuery.data ?? DEFAULT_COLUMNS_PER_CATEGORY}
          readOnly={isDispatched}
        />
      )}

      <ConfirmDialog
        open={overwriteOpen}
        onClose={() => setOverwriteOpen(false)}
        onConfirm={() => saveMutation.mutate(true)}
        title="Overwrite the saved dispatch?"
        description={describeDispatchOverwrite(weekKeyLabel(key), scopeCategoryName)}
        confirmLabel="Overwrite"
        destructive
        pending={saveMutation.isPending}
      />

      <ConfirmDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onConfirm={() => {
          if (isPast && !force) {
            toast.error('Tick "force" to dispatch a past-dated delivery.')
            return
          }
          createMutation.mutate(force)
        }}
        title="Create the individual dispatch?"
        description={`This dispatches ${weekKeyLabel(key)} for real: it snapshots prices and writes negative stock movements. This is the only step that reduces stock.`}
        confirmLabel="Create dispatch"
        pending={createMutation.isPending}
      >
        <dl className="grid grid-cols-3 gap-2 rounded-lg border border-border p-3 text-sm">
          <ConfirmFigure label="Fridges" value={String(totals.fridgesToDispatch)} />
          <ConfirmFigure label="Units" value={String(totals.totalUnits)} />
          <ConfirmFigure label="Value (cost)" value={formatEuro(totals.totalCostEuros)} />
        </dl>
        {isPast ? (
          <label className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
            <input
              type="checkbox"
              checked={force}
              onChange={(event) => setForce(event.target.checked)}
              className="mt-0.5 h-4 w-4"
            />
            <span className="text-foreground">
              This delivery date is in the past. Tick to <strong>force</strong> the dispatch anyway.
            </span>
          </label>
        ) : null}
        <p className="text-xs text-muted-foreground">
          The dispatch Excel file downloads once it is created. If any product would go below zero
          stock, the dispatch is blocked and the affected products are listed.
        </p>
      </ConfirmDialog>

      <UnsavedChangesDialog guard={guard} />
    </div>
  )
}

function describeDispatchOverwrite(keyLabel: string, scopeCategoryName: string | null): string {
  const existing = `A saved dispatch already exists for ${keyLabel}. `
  const noStockEffect = ' Stock is not affected.'
  if (scopeCategoryName === null) {
    return existing + 'Overwriting replaces its planned lines.' + noStockEffect
  }
  return (
    existing +
    `Overwriting replaces only its ${scopeCategoryName} planned lines; ` +
    'the other categories stay as saved.' +
    noStockEffect
  )
}

/** Why "Create Individual Dispatch" is unavailable, or null when it can run. */
function describeCreateBlocker(
  savedDispatch: DispatchRead | null,
  isDirty: boolean,
): string | null {
  if (savedDispatch === null) return 'Save the dispatch first.'
  if (isDirty) return 'Save your changes first: the dispatch is created from the saved lines.'
  return null
}

function describeStockBlocked(
  error: ApiError,
  productMeta: (productId: number) => ProductMeta | null,
): string {
  const entries = Array.isArray(error.details) ? (error.details as StockBlockedEntry[]) : []
  const previewEntries = entries.slice(0, STOCK_BLOCKED_PREVIEW_COUNT)
  const shortages = previewEntries.map((entry) => {
    const name = productMeta(entry.product_id)?.productName ?? `#${entry.product_id}`
    return `${name}: need ${entry.requested}, have ${entry.available}`
  })
  return shortages.join(' · ') || 'Some products would go below zero stock.'
}

function ConfirmFigure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-semibold tabular-nums text-foreground">{value}</dd>
    </div>
  )
}

export default DispatchPage
