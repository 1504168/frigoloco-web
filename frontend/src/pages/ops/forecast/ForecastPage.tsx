import * as React from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, Play, Save, TrendingUp } from 'lucide-react'
import { EmptyState } from '@/components/shared/EmptyState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { api, ApiError } from '@/lib/api'
import { EMPTY_PLACEHOLDER, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { WeekDayPicker } from '@/pages/ops/components/WeekDayPicker'
import { ConfirmDialog } from '@/pages/ops/components/ConfirmDialog'
import { useCategories, useFridgeMap } from '@/pages/ops/lib/reference'
import {
  deliveryDateFromKey,
  useWeekDayKey,
  weekKeyLabel,
  type WeekDayKey,
} from '@/pages/ops/lib/pipelineKey'
import type {
  ForecastActualCell,
  ForecastActuals,
  ForecastResult,
  ForecastRun,
} from '@/pages/ops/lib/types'

/** The only forecast model available today; the selector is future-proofing. */
const FORECAST_MODELS = [{ value: 'moving_average_3w', label: 'Moving average · 3 weeks' }]

const NUMBER_FMT = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 })

/** Ratio (sold/added) → coloured tailwind class: <0.7 red, >=0.9 green, else amber. */
function ratioClass(ratio: string | null): string {
  if (ratio === null) return 'text-muted-foreground'
  const value = Number(ratio)
  if (value < 0.7) return 'text-critical'
  if (value >= 0.9) return 'text-good-text'
  return 'text-warning'
}

/** True when a run belongs to the currently selected pipeline key. */
function runMatchesKey(run: ForecastRun | null, key: WeekDayKey): boolean {
  return (
    !!run &&
    run.iso_year === key.year &&
    run.week_no === key.week &&
    run.day_name.toLowerCase() === key.dayName.toLowerCase()
  )
}

interface ForecastGridProps {
  run: ForecastRun
  fridgeName: (id: number) => string
  categories: { ordered: { id: number; name: string }[]; byId: Map<number, string> }
}

/**
 * Forecast-V2 style grid: fridge rows (name · min qty · days-to-fill from the
 * run's delivery config) × category columns of forecast quantities.
 */
function ForecastGrid({ run, fridgeName, categories }: ForecastGridProps) {
  const cellByKey = React.useMemo(() => {
    const map = new Map<string, ForecastResult>()
    for (const result of run.results) map.set(`${result.fridge_id}:${result.category_id}`, result)
    return map
  }, [run.results])

  const fridgeIds = React.useMemo(() => {
    const ids = Array.from(new Set(run.results.map((result) => result.fridge_id)))
    return ids.sort((a, b) => fridgeName(a).localeCompare(fridgeName(b)))
  }, [run.results, fridgeName])

  const categoryIds = React.useMemo(() => {
    const present = new Set(run.results.map((result) => result.category_id))
    const ordered = categories.ordered
      .filter((category) => present.has(category.id))
      .map((category) => category.id)
    for (const id of present) if (!ordered.includes(id)) ordered.push(id)
    return ordered
  }, [run.results, categories.ordered])

  const fridgeConfig = run.params.fridge_config ?? {}

  const columnTotals = React.useMemo(() => {
    const totals = new Map<number, number>()
    for (const categoryId of categoryIds) {
      let sum = 0
      for (const fridgeId of fridgeIds) {
        sum += Number(cellByKey.get(`${fridgeId}:${categoryId}`)?.forecast_qty ?? 0)
      }
      totals.set(categoryId, sum)
    }
    return totals
  }, [categoryIds, fridgeIds, cellByKey])

  if (fridgeIds.length === 0 || categoryIds.length === 0) {
    return (
      <EmptyState
        title="No forecast rows"
        description="This run produced no fridge × category results. Check that a fridge has a delivery configuration for this weekday."
      />
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="min-w-full border-separate border-spacing-0 text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 border-b border-r border-border bg-card px-3 py-2 text-left font-semibold text-foreground">
              Fridge
            </th>
            <th className="border-b border-border bg-card px-2 py-2 text-right font-semibold text-muted-foreground">
              Min qty
            </th>
            <th className="border-b border-border bg-card px-2 py-2 text-right font-semibold text-muted-foreground">
              Days to fill
            </th>
            {categoryIds.map((categoryId) => (
              <th
                key={categoryId}
                className="border-b border-l border-border bg-card px-3 py-2 text-right font-semibold text-foreground"
                title={categories.byId.get(categoryId)}
              >
                {categories.byId.get(categoryId) ?? `#${categoryId}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fridgeIds.map((fridgeId) => {
            const config = fridgeConfig[String(fridgeId)]
            return (
              <tr key={fridgeId} className="hover:bg-accent/30">
                <td className="sticky left-0 z-10 border-b border-r border-border bg-card px-3 py-1.5 font-medium text-foreground">
                  {fridgeName(fridgeId)}
                </td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                  {config ? config.min_daily_qty : EMPTY_PLACEHOLDER}
                </td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                  {config ? config.days_to_fill : EMPTY_PLACEHOLDER}
                </td>
                {categoryIds.map((categoryId) => {
                  const cell = cellByKey.get(`${fridgeId}:${categoryId}`)
                  const qty = cell ? Number(cell.forecast_qty) : 0
                  return (
                    <td
                      key={categoryId}
                      title={
                        cell ? `${cell.valid_days} valid days · ${cell.holiday_days} holiday` : undefined
                      }
                      className={cn(
                        'border-b border-l border-border px-3 py-1.5 text-right tabular-nums',
                        qty === 0 ? 'text-muted-foreground/40' : 'text-foreground',
                      )}
                    >
                      {qty === 0 ? '·' : NUMBER_FMT.format(qty)}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <th className="sticky left-0 z-10 border-t-2 border-r border-border bg-card px-3 py-2 text-left font-semibold text-foreground">
              Total
            </th>
            <td className="border-t-2 border-border bg-card" />
            <td className="border-t-2 border-border bg-card" />
            {categoryIds.map((categoryId) => (
              <td
                key={categoryId}
                className="border-l border-t-2 border-border bg-card px-3 py-2 text-right font-semibold tabular-nums text-foreground"
              >
                {NUMBER_FMT.format(columnTotals.get(categoryId) ?? 0)}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

interface ActualsGridProps {
  run: ForecastRun
  actuals: ForecastActuals
  fridgeName: (id: number) => string
  categories: { ordered: { id: number; name: string }[]; byId: Map<number, string> }
}

/**
 * Actuals side block: the same fridge × category axes as the forecast grid,
 * showing added → sold quantities over the forecast's 3-week window with a
 * colour-coded sell-through ratio. Fridge/category keys with no recorded
 * activity render as 0 → 0 with an em-dash ratio.
 */
function ActualsGrid({ run, actuals, fridgeName, categories }: ActualsGridProps) {
  const cellByKey = React.useMemo(() => {
    const map = new Map<string, ForecastActualCell>()
    for (const cell of actuals.cells) map.set(`${cell.fridge_id}:${cell.category_id}`, cell)
    return map
  }, [actuals.cells])

  // Axes follow the forecast run so the two grids line up row-for-row.
  const fridgeIds = React.useMemo(() => {
    const ids = Array.from(new Set(run.results.map((result) => result.fridge_id)))
    return ids.sort((a, b) => fridgeName(a).localeCompare(fridgeName(b)))
  }, [run.results, fridgeName])

  const categoryIds = React.useMemo(() => {
    const present = new Set(run.results.map((result) => result.category_id))
    const ordered = categories.ordered
      .filter((category) => present.has(category.id))
      .map((category) => category.id)
    for (const id of present) if (!ordered.includes(id)) ordered.push(id)
    return ordered
  }, [run.results, categories.ordered])

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="min-w-full border-separate border-spacing-0 text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 border-b border-r border-border bg-card px-3 py-2 text-left font-semibold text-foreground">
              Fridge
            </th>
            {categoryIds.map((categoryId) => (
              <th
                key={categoryId}
                className="border-b border-l border-border bg-card px-3 py-2 text-right font-semibold text-foreground"
                title={categories.byId.get(categoryId)}
              >
                {categories.byId.get(categoryId) ?? `#${categoryId}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fridgeIds.map((fridgeId) => (
            <tr key={fridgeId} className="hover:bg-accent/30">
              <td className="sticky left-0 z-10 border-b border-r border-border bg-card px-3 py-1.5 font-medium text-foreground">
                {fridgeName(fridgeId)}
              </td>
              {categoryIds.map((categoryId) => {
                const cell = cellByKey.get(`${fridgeId}:${categoryId}`)
                const added = cell?.added_qty ?? 0
                const sold = cell?.sold_qty ?? 0
                const ratio = cell?.ratio ?? null
                return (
                  <td
                    key={categoryId}
                    className="border-b border-l border-border px-3 py-1.5 text-right align-top"
                    title="Added → Sold · ratio = sold ÷ added"
                  >
                    <div className="tabular-nums text-foreground">
                      {added} → {sold}
                    </div>
                    <div className={cn('text-[11px] font-medium tabular-nums', ratioClass(ratio))}>
                      {ratio === null ? EMPTY_PLACEHOLDER : Number(ratio).toFixed(2)}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ForecastPage() {
  const { key, setKey } = useWeekDayKey()
  const [model, setModel] = React.useState(FORECAST_MODELS[0].value)
  const [run, setRun] = React.useState<ForecastRun | null>(null)
  const [overwriteOpen, setOverwriteOpen] = React.useState(false)

  const fridgeMapQuery = useFridgeMap()
  const categoriesQuery = useCategories()

  const fridgeName = React.useCallback(
    (id: number) => fridgeMapQuery.data?.get(id) ?? `Fridge #${id}`,
    [fridgeMapQuery.data],
  )

  const deliveryDate = deliveryDateFromKey(key)
  const showRun = runMatchesKey(run, key)

  // Actuals for the same pipeline key: fetched only once a forecast is on screen.
  const actualsQuery = useQuery({
    queryKey: ['ops', 'forecast', 'actuals', key.year, key.week, key.dayName],
    queryFn: ({ signal }) =>
      api.get<ForecastActuals>('/api/v1/forecasts/actuals', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
        signal,
      }),
    enabled: showRun,
    staleTime: 60_000,
  })

  const runMutation = useMutation({
    mutationFn: () =>
      api.post<ForecastRun>('/api/v1/forecasts/run', { delivery_date: deliveryDate, model }),
    onSuccess: (result) => {
      setRun(result)
      toast.success(`Forecast computed: ${result.results.length} rows for ${result.delivery_date}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'no_delivery_config') {
        toast.error('No fridge has a delivery configuration for this weekday.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to run forecast')
      }
    },
  })

  const loadSavedMutation = useMutation({
    mutationFn: () =>
      api.get<ForecastRun>('/api/v1/forecasts/saved', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
      }),
    onSuccess: (result) => {
      setRun(result)
      setModel(result.model)
      toast.success(`Loaded saved forecast for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved forecast for this key yet.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to load saved forecast')
      }
    },
  })

  const saveMutation = useMutation({
    mutationFn: (overwrite: boolean) =>
      api.post<ForecastRun>('/api/v1/forecasts/save', {
        year: key.year,
        week: key.week,
        day_name: key.dayName,
        model,
        overwrite,
      }),
    onSuccess: (result) => {
      setRun(result)
      setOverwriteOpen(false)
      toast.success(`Forecast saved for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'exists') {
        setOverwriteOpen(true)
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to save forecast')
    },
  })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <WeekDayPicker value={key} onChange={setKey} />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select value={model} onValueChange={setModel}>
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FORECAST_MODELS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={() => loadSavedMutation.mutate()}
            disabled={loadSavedMutation.isPending}
          >
            <Download className="h-4 w-4" />
            {loadSavedMutation.isPending ? 'Loading…' : 'Load saved'}
          </Button>
          <Button onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
            <Play className="h-4 w-4" />
            {runMutation.isPending ? 'Running…' : 'Run'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => saveMutation.mutate(false)}
            disabled={saveMutation.isPending}
          >
            <Save className="h-4 w-4" />
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-foreground">
            {weekKeyLabel(key)}
            <span className="ml-2 font-normal text-muted-foreground">delivery {deliveryDate}</span>
          </h2>
          {showRun && run ? (
            <span className="text-xs text-muted-foreground">
              Run #{run.run_id} · {run.is_saved ? 'saved' : 'unsaved'} · {formatDateTime(run.run_at)}
            </span>
          ) : null}
        </div>

        {runMutation.isPending || loadSavedMutation.isPending ? (
          <LoadingSkeleton rows={6} columns={6} />
        ) : !showRun ? (
          <EmptyState
            icon={<TrendingUp className="h-8 w-8" />}
            title="No forecast loaded"
            description="Run the forecast for this week/day, or load a previously saved one."
          />
        ) : categoriesQuery.data && run ? (
          <>
            <ForecastGrid run={run} fridgeName={fridgeName} categories={categoriesQuery.data} />
            <div className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-xs font-semibold text-foreground">
                  Actuals · Added → Sold · ratio
                  {actualsQuery.data ? (
                    <span className="ml-2 font-normal text-muted-foreground">
                      3-week window {actualsQuery.data.window_start} → {actualsQuery.data.window_end}
                    </span>
                  ) : null}
                </h3>
                <span className="text-[11px] text-muted-foreground">
                  ratio = sold ÷ added · <span className="text-critical">&lt;0.70</span> ·{' '}
                  <span className="text-warning">0.70–0.89</span> ·{' '}
                  <span className="text-good-text">≥0.90</span>
                </span>
              </div>
              {actualsQuery.isLoading ? (
                <LoadingSkeleton rows={4} columns={4} />
              ) : actualsQuery.isError ? (
                <EmptyState
                  title="Actuals unavailable"
                  description={
                    actualsQuery.error instanceof ApiError
                      ? actualsQuery.error.message
                      : 'Failed to load actuals for this key.'
                  }
                />
              ) : actualsQuery.data ? (
                <ActualsGrid
                  run={run}
                  actuals={actualsQuery.data}
                  fridgeName={fridgeName}
                  categories={categoriesQuery.data}
                />
              ) : null}
            </div>
          </>
        ) : (
          <LoadingSkeleton rows={6} columns={6} />
        )}
      </section>

      <ConfirmDialog
        open={overwriteOpen}
        onClose={() => setOverwriteOpen(false)}
        onConfirm={() => saveMutation.mutate(true)}
        title="Overwrite the saved forecast?"
        description={`A saved forecast already exists for ${weekKeyLabel(key)}. Overwriting deletes the prior rows and re-saves this run.`}
        confirmLabel="Overwrite"
        destructive
        pending={saveMutation.isPending}
      />
    </div>
  )
}

export default ForecastPage
