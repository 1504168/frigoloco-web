import * as React from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, Save, Truck } from 'lucide-react'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { StatusChip } from '@/components/shared/StatusChip'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/sonner'
import { api, ApiError } from '@/lib/api'
import { formatEuro } from '@/lib/format'
import { WeekDayPicker } from '@/pages/ops/components/WeekDayPicker'
import { ConfirmDialog } from '@/pages/ops/components/ConfirmDialog'
import { PlanningGrid } from '@/pages/ops/components/PlanningGrid'
import { useMenuCategoryColumns, useProductCatalogue } from '@/pages/ops/lib/reference'
import { usePlanningGridState, useProductMeta } from '@/pages/ops/lib/grid'
import { keyIsPast, useWeekDayKey, weekKeyLabel } from '@/pages/ops/lib/pipelineKey'
import type {
  ConfirmResult,
  DispatchMatrix,
  DispatchRead,
  DispatchStatus,
  StockBlockedEntry,
} from '@/pages/ops/lib/types'

export function DispatchPage() {
  const { key, setKey } = useWeekDayKey()
  const grid = usePlanningGridState()
  const { meta: productMeta, isLoading: metaLoading } = useProductMeta()

  const catalogueQuery = useProductCatalogue()
  const columnsQuery = useMenuCategoryColumns()

  const [loaded, setLoaded] = React.useState(false)
  const [status, setStatus] = React.useState<DispatchStatus | null>(null)
  const [overwriteOpen, setOverwriteOpen] = React.useState(false)
  const [createOpen, setCreateOpen] = React.useState(false)
  const [force, setForce] = React.useState(false)

  const isPast = keyIsPast(key)

  // Any stage change clears the current grid - it belongs to another key.
  React.useEffect(() => {
    setLoaded(false)
    setStatus(null)
    setForce(false)
  }, [key.year, key.week, key.dayName])

  const importMutation = useMutation({
    mutationFn: () =>
      api.post<DispatchMatrix>('/api/v1/dispatches/import-from-menu', undefined, {
        params: { year: key.year, week: key.week, day_name: key.dayName },
      }),
    onSuccess: (matrix) => {
      grid.loadFromGrid(matrix)
      setStatus(null)
      setLoaded(true)
      toast.success(`Imported ${matrix.products.length} products from the saved menu`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved menu for this key - save a menu first.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to import from menu')
      }
    },
  })

  const loadSavedMutation = useMutation({
    mutationFn: async () => {
      const saved = await api.get<DispatchRead>('/api/v1/dispatches/saved', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
      })
      const matrix = await api.get<DispatchMatrix>(`/api/v1/dispatches/${saved.id}/matrix`)
      return { saved, matrix }
    },
    onSuccess: ({ saved, matrix }) => {
      grid.loadFromGrid(matrix)
      setStatus(saved.status)
      setLoaded(true)
      toast.success(`Loaded saved dispatch for ${weekKeyLabel(key)} (${saved.status})`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved dispatch for this key yet.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to load saved dispatch')
      }
    },
  })

  // Auto-load the saved dispatch for the selected date if one exists (silent
  // when none). Fires whenever the week/day key changes; never overrides edits.
  const savedDispatchQuery = useQuery({
    queryKey: ['ops', 'dispatch', 'saved', key.year, key.week, key.dayName],
    queryFn: async ({ signal }) => {
      const saved = await api.get<DispatchRead>('/api/v1/dispatches/saved', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
        signal,
      })
      const matrix = await api.get<DispatchMatrix>(`/api/v1/dispatches/${saved.id}/matrix`, {
        signal,
      })
      return { saved, matrix }
    },
    retry: false,
  })

  React.useEffect(() => {
    const data = savedDispatchQuery.data
    if (data && !savedDispatchQuery.isFetching && !loaded) {
      grid.loadFromGrid(data.matrix)
      setStatus(data.saved.status)
      setLoaded(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedDispatchQuery.data, savedDispatchQuery.isFetching, loaded])

  const saveMutation = useMutation({
    mutationFn: (overwrite: boolean) =>
      api.post<DispatchRead>('/api/v1/dispatches/save', {
        year: key.year,
        week: key.week,
        day_name: key.dayName,
        lines: grid.toLines(),
        overwrite,
      }),
    onSuccess: (saved) => {
      setStatus(saved.status)
      setOverwriteOpen(false)
      toast.success('Dispatch saved as planned', {
        description: 'Stock is NOT reduced by saving - only "Create Individual Dispatch" moves stock.',
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
    mutationFn: (forceCreate: boolean) =>
      api.post<ConfirmResult>('/api/v1/dispatches/create-individual', undefined, {
        params: {
          year: key.year,
          week: key.week,
          day_name: key.dayName,
          force: forceCreate,
        },
      }),
    onSuccess: (result) => {
      setStatus(result.status)
      setCreateOpen(false)
      toast.success(`Dispatch created: ${result.movements_created} stock movements`, {
        description: 'Stock has been reduced for every dispatched product.',
      })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'stock_blocked') {
        const entries = Array.isArray(error.details) ? (error.details as StockBlockedEntry[]) : []
        const detail = entries
          .slice(0, 6)
          .map((entry) => {
            const name = productMeta(entry.product_id)?.productName ?? `#${entry.product_id}`
            return `${name}: need ${entry.requested}, have ${entry.available}`
          })
          .join(' · ')
        toast.error('Stock blocked - dispatch not created', {
          description: detail || 'Some products would go below zero stock.',
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

  const isBusy = importMutation.isPending || loadSavedMutation.isPending
  const isDispatched = status === 'dispatched' || status === 'reconciled'
  const canSave = grid.fridges.length > 0 && grid.productIds.size > 0 && !isDispatched

  // Summary line (mirrors the legacy Dispatch View totals): units and cost value
  // (purchase price x qty) across the grid, plus fridge coverage.
  const dispatchLines = grid.toLines()
  const totalUnits = dispatchLines.reduce((sum, line) => sum + line.qty, 0)
  const totalValueEuros = dispatchLines.reduce((sum, line) => {
    const price = Number(productMeta(line.product_id)?.purchasePrice ?? 0)
    return Number.isFinite(price) ? sum + line.qty * price : sum
  }, 0)
  const fridgesToDispatch = new Set(dispatchLines.map((line) => line.fridge_id)).size

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <WeekDayPicker value={key} onChange={setKey} />
          {status ? <StatusChip status={status} /> : null}
          {isPast ? <StatusChip variant="warning" label="Past date" /> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={() => importMutation.mutate()}
            disabled={importMutation.isPending}
          >
            <Download className="h-4 w-4" />
            {importMutation.isPending ? 'Importing…' : 'From Menu'}
          </Button>
          <Button
            variant="outline"
            onClick={() => loadSavedMutation.mutate()}
            disabled={loadSavedMutation.isPending}
          >
            <Download className="h-4 w-4" />
            {loadSavedMutation.isPending ? 'Loading…' : 'Load saved'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => saveMutation.mutate(false)}
            disabled={saveMutation.isPending || !canSave}
          >
            <Save className="h-4 w-4" />
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
          <Button
            onClick={() => {
              setForce(false)
              setCreateOpen(true)
            }}
            disabled={createMutation.isPending || isDispatched || !loaded}
          >
            <Truck className="h-4 w-4" />
            Create Individual Dispatch
          </Button>
        </div>
      </div>

      {loaded && grid.hasData ? (
        <div className="flex flex-wrap divide-x divide-border overflow-hidden rounded-xl border border-border bg-card">
          <SummaryStat label="Fridges" value={String(grid.fridges.length)} />
          <SummaryStat label="Fridges to dispatch" value={String(fridgesToDispatch)} />
          <SummaryStat label="Total units" value={String(totalUnits)} />
          <SummaryStat label="Total value (cost)" value={formatEuro(totalValueEuros)} />
        </div>
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
          columnsPerCategory={columnsQuery.data ?? 6}
          readOnly={isDispatched}
        />
      )}

      <ConfirmDialog
        open={overwriteOpen}
        onClose={() => setOverwriteOpen(false)}
        onConfirm={() => saveMutation.mutate(true)}
        title="Overwrite the saved dispatch?"
        description={`A saved dispatch already exists for ${weekKeyLabel(key)}. Overwriting replaces its planned lines. Stock is not affected.`}
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
          If any product would go below zero stock, the backend blocks the dispatch and lists the
          affected products.
        </p>
      </ConfirmDialog>
    </div>
  )
}

/** One labelled figure in the dispatch summary bar. */
function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-[10rem] flex-1 flex-col gap-1 px-5 py-3">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="text-xl font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  )
}

export default DispatchPage
