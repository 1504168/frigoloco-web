import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Play, TrendingUp } from 'lucide-react'
import { SaveIconButton } from '@/components/shared/SaveIconButton'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { EmptyState } from '@/components/shared/EmptyState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Toolbar } from '@/components/shared/Toolbar'
import { UnsavedChangesDialog } from '@/components/shared/UnsavedChangesDialog'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { useUnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard'
import { api, ApiError } from '@/lib/api'
import { WeekDayPicker } from '@/pages/ops/components/WeekDayPicker'
import { useCategories, useFridgeMap } from '@/pages/ops/lib/reference'
import {
  deliveryDateFromKey,
  useWeekDayKey,
  weekKeyLabel,
  type WeekDayKey,
} from '@/pages/ops/lib/pipelineKey'
import type {
  ForecastActuals,
  ForecastModel,
  ForecastRun,
  ForecastSaveRequest,
} from '@/pages/ops/lib/types'
import { ForecastGrid } from './ForecastGrid'
import { ForecastNotices } from './ForecastNotices'
import {
  cellsFromDraft,
  countInvalidCells,
  draftFromRun,
  isDraftChanged,
  roundDraft,
  ROUND_MODE_OPTIONS,
  type ForecastDraft,
  type RoundMode,
} from './forecastDraft'

const DEFAULT_MODEL = 'moving_average_3w'
const SAVED_FORECAST_KEY = ['ops', 'forecast', 'saved'] as const
const ACTUALS_STALE_MS = 60_000

/** True when a run belongs to the currently selected pipeline key. */
function runMatchesKey(run: ForecastRun | null, key: WeekDayKey): run is ForecastRun {
  return (
    run !== null &&
    run.iso_year === key.year &&
    run.week_no === key.week &&
    run.day_name.toLowerCase() === key.dayName.toLowerCase()
  )
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function ForecastPage() {
  const queryClient = useQueryClient()
  const { key, setKey } = useWeekDayKey()
  const [model, setModel] = React.useState(DEFAULT_MODEL)
  const [run, setRun] = React.useState<ForecastRun | null>(null)
  const [draft, setDraft] = React.useState<ForecastDraft>({})
  const [showHiddenCategories, setShowHiddenCategories] = React.useState(false)
  const [overwriteOpen, setOverwriteOpen] = React.useState(false)

  const fridgeMapQuery = useFridgeMap()
  const categoriesQuery = useCategories()
  const modelsQuery = useQuery({
    queryKey: ['ops', 'forecast', 'models'],
    queryFn: ({ signal }) => api.get<ForecastModel[]>('/api/v1/forecasts/models', { signal }),
    staleTime: Infinity,
  })

  const fridgeName = React.useCallback(
    (id: number) => fridgeMapQuery.data?.get(id) ?? `Fridge #${id}`,
    [fridgeMapQuery.data],
  )
  const categoryName = React.useCallback(
    (id: number) => categoriesQuery.data?.byId.get(id) ?? `#${id}`,
    [categoriesQuery.data],
  )

  const shownRun = runMatchesKey(run, key) ? run : null
  const isDirty = shownRun !== null && isDraftChanged(shownRun, draft)
  const invalidCellCount = shownRun === null ? 0 : countInvalidCells(draft)
  const guard = useUnsavedChangesGuard(isDirty)

  const showForecast = React.useCallback((next: ForecastRun) => {
    setRun(next)
    setDraft(draftFromRun(next))
    setModel(next.model)
  }, [])

  const actualsQuery = useQuery({
    queryKey: ['ops', 'forecast', 'actuals', key.year, key.week, key.dayName, shownRun?.model],
    queryFn: ({ signal }) =>
      api.get<ForecastActuals>('/api/v1/forecasts/actuals', {
        params: {
          year: key.year,
          week: key.week,
          day_name: key.dayName,
          model: shownRun?.model,
        },
        signal,
      }),
    enabled: shownRun !== null,
    staleTime: ACTUALS_STALE_MS,
  })

  // Shows the saved forecast for the selected key when nothing for that key is on screen.
  const savedRunQuery = useQuery({
    queryKey: [...SAVED_FORECAST_KEY, key.year, key.week, key.dayName],
    queryFn: ({ signal }) =>
      api.get<ForecastRun>('/api/v1/forecasts/saved', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
        signal,
      }),
    retry: false,
  })

  React.useEffect(() => {
    const saved = savedRunQuery.data
    if (saved === undefined || runMatchesKey(run, key)) return
    if (runMatchesKey(saved, key)) showForecast(saved)
  }, [savedRunQuery.data, key, run, showForecast])

  const runMutation = useMutation({
    mutationFn: () =>
      api.post<ForecastRun>('/api/v1/forecasts/run', {
        delivery_date: deliveryDateFromKey(key),
        model,
      }),
    onSuccess: (result) => {
      showForecast(result)
      toast.success(`Forecast computed for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'no_delivery_config') {
        toast.error('No fridge has a delivery configuration for this weekday.')
        return
      }
      toast.error(errorMessage(error, 'Failed to run forecast'))
    },
  })

  const loadSavedMutation = useMutation({
    mutationFn: () =>
      api.get<ForecastRun>('/api/v1/forecasts/saved', {
        params: { year: key.year, week: key.week, day_name: key.dayName },
      }),
    onSuccess: (result) => {
      showForecast(result)
      toast.success(`Loaded saved forecast for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved forecast for this key yet.')
        return
      }
      toast.error(errorMessage(error, 'Failed to load saved forecast'))
    },
  })

  const saveMutation = useMutation({
    mutationFn: ({ shown, overwrite }: { shown: ForecastRun; overwrite: boolean }) => {
      const body: ForecastSaveRequest = {
        run_id: shown.run_id,
        cells: cellsFromDraft(shown, draft),
        overwrite,
      }
      return api.post<ForecastRun>('/api/v1/forecasts/save', body)
    },
    onSuccess: (result) => {
      showForecast(result)
      setOverwriteOpen(false)
      queryClient.invalidateQueries({ queryKey: SAVED_FORECAST_KEY })
      toast.success(`Forecast saved for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'exists') {
        setOverwriteOpen(true)
        return
      }
      setOverwriteOpen(false)
      toast.error(`Forecast not saved: ${errorMessage(error, 'unexpected error')}`)
    },
  })

  function changeKey(next: WeekDayKey) {
    guard.confirmDiscard(() => {
      setRun(null)
      setKey(next)
    })
  }

  function saveShownForecast(overwrite: boolean) {
    if (shownRun === null) return
    saveMutation.mutate({ shown: shownRun, overwrite })
  }

  function updateCell(cellId: string, text: string) {
    setDraft((current) => ({ ...current, [cellId]: text }))
  }

  function roundAllCells(mode: RoundMode) {
    setDraft((current) => roundDraft(current, mode))
  }

  const hiddenCategoryIds = new Set(shownRun?.hidden_category_ids ?? [])
  const runCategoryIds = new Set(shownRun?.results.map((result) => result.category_id) ?? [])
  const visibleCategoryIds = (categoriesQuery.data?.ordered ?? [])
    .map((category) => category.id)
    .filter((id) => runCategoryIds.has(id))
    .filter((id) => showHiddenCategories || !hiddenCategoryIds.has(id))
  const modelOptions = modelsQuery.data ?? []
  const modelLabel = (code: string) =>
    modelOptions.find((option) => option.code === code)?.label ?? code
  const isBusy = runMutation.isPending || loadSavedMutation.isPending
  const hasInvalidCells = invalidCellCount > 0
  const invalidCellsMessage = `${invalidCellCount} cell(s) need a number of 0 or more before saving.`
  const hasSomethingToSave = shownRun !== null && (!shownRun.is_saved || isDirty)
  const canSave = hasSomethingToSave && !hasInvalidCells && !saveMutation.isPending

  return (
    <div className="space-y-3">
      {/* Wraps instead of overlapping when the window is too narrow for one row. */}
      <Toolbar
        className="lg:flex-wrap"
        left={
          <>
            <WeekDayPicker value={key} onChange={changeKey} compact />
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger className="h-9 w-56" aria-label="Forecast method">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((option) => (
                  <SelectItem key={option.code} value={option.code}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* An action menu, not a setting: the value stays empty so every pick rounds again. */}
            <Select
              value=""
              onValueChange={(mode) => roundAllCells(mode as RoundMode)}
              disabled={shownRun === null}
            >
              <SelectTrigger className="h-9 w-32" aria-label="Round all quantities">
                <SelectValue placeholder="Round all" />
              </SelectTrigger>
              <SelectContent>
                {ROUND_MODE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        }
        right={
          <>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              title="Load the saved forecast for this day"
              onClick={() => guard.confirmDiscard(() => loadSavedMutation.mutate())}
              disabled={loadSavedMutation.isPending}
            >
              <Download className="h-4 w-4" />
              {loadSavedMutation.isPending ? 'Loading…' : 'Load'}
            </Button>
            <Button
              size="sm"
              className="h-9"
              onClick={() => guard.confirmDiscard(() => runMutation.mutate())}
              disabled={runMutation.isPending}
            >
              <Play className="h-4 w-4" />
              {runMutation.isPending ? 'Running…' : 'Run'}
            </Button>
            <SaveIconButton
              label="Save forecast"
              variant="secondary"
              onClick={() => saveShownForecast(false)}
              disabled={!canSave}
              isSaving={saveMutation.isPending}
              disabledReason={hasInvalidCells ? invalidCellsMessage : undefined}
            />
          </>
        }
      />

      <section className="space-y-3">
        <ForecastContent
          isBusy={isBusy}
          shownRun={shownRun}
          hasCategories={categoriesQuery.data !== undefined}
          renderRun={(current) => (
            <>
              <ForecastNotices
                run={current}
                modelLabel={modelLabel(current.model)}
                viewOptions={
                  hiddenCategoryIds.size > 0 && (
                    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={showHiddenCategories}
                        onChange={(event) => setShowHiddenCategories(event.target.checked)}
                      />
                      Show hidden categories ({hiddenCategoryIds.size})
                    </label>
                  )
                }
              />
              {hasInvalidCells && <p className="text-xs text-critical">{invalidCellsMessage}</p>}
              <ForecastGrid
                run={current}
                draft={draft}
                onCellChange={updateCell}
                actuals={actualsQuery.data ?? null}
                fridgeName={fridgeName}
                categoryIds={visibleCategoryIds}
                categoryName={categoryName}
              />
            </>
          )}
        />
      </section>

      <ConfirmDialog
        open={overwriteOpen}
        onClose={() => setOverwriteOpen(false)}
        onConfirm={() => saveShownForecast(true)}
        title="Overwrite the saved forecast?"
        description={`A saved forecast already exists for ${weekKeyLabel(key)}. Overwriting replaces it with the quantities on screen.`}
        confirmLabel="Overwrite"
        destructive
        pending={saveMutation.isPending}
      />
      <UnsavedChangesDialog guard={guard} />
    </div>
  )
}

interface ForecastContentProps {
  isBusy: boolean
  shownRun: ForecastRun | null
  hasCategories: boolean
  renderRun: (run: ForecastRun) => React.ReactNode
}

function ForecastContent({ isBusy, shownRun, hasCategories, renderRun }: ForecastContentProps) {
  if (isBusy) return <LoadingSkeleton rows={6} columns={6} />
  if (shownRun === null) {
    return (
      <EmptyState
        icon={<TrendingUp className="h-8 w-8" />}
        title="No forecast loaded"
        description="Run the forecast for this week/day, or load a previously saved one."
      />
    )
  }
  if (!hasCategories) return <LoadingSkeleton rows={6} columns={6} />
  return renderRun(shownRun)
}

export default ForecastPage
