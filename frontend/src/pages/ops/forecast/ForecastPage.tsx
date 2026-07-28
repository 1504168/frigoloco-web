import * as React from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Download, Play, Save, TrendingUp } from 'lucide-react'
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
import { EMPTY_PLACEHOLDER } from '@/lib/format'
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

/** Sell-through ratio as a colour-coded percentage with an up/down trend icon. */
function RatioBadge({ ratio }: { ratio: string | null }) {
  if (ratio === null) {
    return <span className="text-muted-foreground">{EMPTY_PLACEHOLDER}</span>
  }
  const value = Number(ratio)
  const Icon = value < 0.7 ? ArrowDown : ArrowUp
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 font-medium tabular-nums',
        ratioClass(ratio),
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      {Math.round(value * 100)}%
    </span>
  )
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
  actuals: ForecastActuals | null
  fridgeName: (id: number) => string
  categories: { ordered: { id: number; name: string }[]; byId: Map<number, string> }
}

const CATEGORY_HEAD_CLASS =
  'min-w-[7rem] whitespace-nowrap border-b border-l border-border bg-card px-3 py-2 text-center font-semibold text-foreground'

/**
 * Forecast-V2 grid: fridge rows (name · min · days-to-fill) × category columns.
 * The forecast quantities sit on the left; the same fridge × category axes then
 * repeat on the right (past a heavier divider) as the Added → Sold actuals, so a
 * single fridge line shows both its forecast and its sell-through together.
 * Wide, so it scrolls horizontally.
 */
function ForecastGrid({ run, actuals, fridgeName, categories }: ForecastGridProps) {
  const cellByKey = React.useMemo(() => {
    const map = new Map<string, ForecastResult>()
    for (const result of run.results) map.set(`${result.fridge_id}:${result.category_id}`, result)
    return map
  }, [run.results])

  const actualByKey = React.useMemo(() => {
    const map = new Map<string, ForecastActualCell>()
    for (const cell of actuals?.cells ?? []) map.set(`${cell.fridge_id}:${cell.category_id}`, cell)
    return map
  }, [actuals])

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

  const categoryLabel = (categoryId: number) => categories.byId.get(categoryId) ?? `#${categoryId}`

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="min-w-full border-separate border-spacing-0 text-xs">
        <thead>
          <tr>
            <th
              rowSpan={2}
              className="sticky left-0 z-10 whitespace-nowrap border-b border-r border-border bg-card px-3 py-2 text-left align-bottom font-semibold text-foreground"
            >
              Fridge
            </th>
            <th
              rowSpan={2}
              className="border-b border-border bg-card px-2 py-2 text-right align-bottom font-semibold text-muted-foreground"
            >
              Min
            </th>
            <th
              rowSpan={2}
              className="border-b border-border bg-card px-2 py-2 text-right align-bottom font-semibold text-muted-foreground"
            >
              Days
            </th>
            <th
              colSpan={categoryIds.length}
              className="border-b border-l-2 border-border bg-card px-3 py-1.5 text-center font-semibold text-foreground"
            >
              Forecast (QTY)
            </th>
            <th
              colSpan={categoryIds.length}
              className="border-b border-l-2 border-border bg-card px-3 py-1.5 text-center font-semibold text-foreground"
            >
              Added → Sold Ratio
            </th>
          </tr>
          <tr>
            {categoryIds.map((categoryId, index) => (
              <th
                key={`f-${categoryId}`}
                className={cn(CATEGORY_HEAD_CLASS, index === 0 && 'border-l-2')}
                title={categories.byId.get(categoryId)}
              >
                {categoryLabel(categoryId)}
              </th>
            ))}
            {categoryIds.map((categoryId, index) => (
              <th
                key={`a-${categoryId}`}
                className={cn(CATEGORY_HEAD_CLASS, index === 0 && 'border-l-2')}
                title={categories.byId.get(categoryId)}
              >
                {categoryLabel(categoryId)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fridgeIds.map((fridgeId) => {
            const config = fridgeConfig[String(fridgeId)]
            return (
              <tr key={fridgeId} className="hover:bg-accent/30">
                <td className="sticky left-0 z-10 whitespace-nowrap border-b border-r border-border bg-card px-3 py-1.5 font-medium text-foreground">
                  {fridgeName(fridgeId)}
                </td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                  {config ? config.min_daily_qty : EMPTY_PLACEHOLDER}
                </td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                  {config ? config.days_to_fill : EMPTY_PLACEHOLDER}
                </td>
                {categoryIds.map((categoryId, index) => {
                  const cell = cellByKey.get(`${fridgeId}:${categoryId}`)
                  const qty = cell ? Number(cell.forecast_qty) : 0
                  return (
                    <td
                      key={`f-${categoryId}`}
                      title={
                        cell ? `${cell.valid_days} valid days · ${cell.holiday_days} holiday` : undefined
                      }
                      className={cn(
                        'border-b border-l border-border px-3 py-1.5 text-center tabular-nums',
                        index === 0 && 'border-l-2',
                        qty === 0 ? 'text-muted-foreground/40' : 'text-foreground',
                      )}
                    >
                      {qty === 0 ? '' : NUMBER_FMT.format(qty)}
                    </td>
                  )
                })}
                {categoryIds.map((categoryId, index) => {
                  const actualCell = actualByKey.get(`${fridgeId}:${categoryId}`)
                  const added = actualCell?.added_qty ?? 0
                  const sold = actualCell?.sold_qty ?? 0
                  const ratio = actualCell?.ratio ?? null
                  return (
                    <td
                      key={`a-${categoryId}`}
                      title="Added → Sold · ratio = sold ÷ added"
                      className={cn(
                        'border-b border-l border-border px-3 py-1.5 text-right',
                        index === 0 && 'border-l-2',
                      )}
                    >
                      {actuals !== null && (
                        <div className="flex items-center justify-center gap-1.5 whitespace-nowrap">
                          <span className="tabular-nums text-foreground">
                            {added} → {sold}
                          </span>
                          <RatioBadge ratio={ratio} />
                        </div>
                      )}
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
            {categoryIds.map((categoryId, index) => (
              <td
                key={`ft-${categoryId}`}
                className={cn(
                  'border-l border-t-2 border-border bg-card px-3 py-2 text-center font-semibold tabular-nums text-foreground',
                  index === 0 && 'border-l-2',
                )}
              >
                {NUMBER_FMT.format(columnTotals.get(categoryId) ?? 0)}
              </td>
            ))}
            {categoryIds.map((categoryId, index) => (
              <td
                key={`at-${categoryId}`}
                className={cn('border-l border-t-2 border-border bg-card', index === 0 && 'border-l-2')}
              />
            ))}
          </tr>
        </tfoot>
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

  // Auto-load the saved forecast for the selected date if one exists (silent
  // when none). Fires whenever the week/day key changes.
  const savedRunQuery = useQuery({
    queryKey: ['ops', 'forecast', 'saved', key.year, key.week, key.dayName],
    queryFn: ({ signal }) =>
      api.get<ForecastRun>('/api/v1/forecasts/saved', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
        signal,
      }),
    retry: false,
  })

  React.useEffect(() => {
    const saved = savedRunQuery.data
    if (saved && runMatchesKey(saved, key) && !runMatchesKey(run, key)) {
      setRun(saved)
      setModel(saved.model)
    }
  }, [savedRunQuery.data, key, run])

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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <WeekDayPicker value={key} onChange={setKey} />
        <div className="flex flex-wrap items-center gap-2">
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
        {runMutation.isPending || loadSavedMutation.isPending ? (
          <LoadingSkeleton rows={6} columns={6} />
        ) : !showRun ? (
          <EmptyState
            icon={<TrendingUp className="h-8 w-8" />}
            title="No forecast loaded"
            description="Run the forecast for this week/day, or load a previously saved one."
          />
        ) : categoriesQuery.data && run ? (
          <ForecastGrid
            run={run}
            actuals={actualsQuery.data ?? null}
            fridgeName={fridgeName}
            categories={categoriesQuery.data}
          />
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
