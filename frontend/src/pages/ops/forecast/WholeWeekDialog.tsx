import * as React from 'react'
import { Modal } from '@/components/shared/Modal'
import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'
import { deliveryDateFromKey, type WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import type { ForecastRun, ForecastSaveRequest } from '@/pages/ops/lib/types'
import { useBankHolidays } from './forecastQueries'
import { cellsFromDraft, draftFromRun } from './forecastDraft'
import { daysOfWeek, weekLabel } from './forecastWeeks'

type DayOutcome = 'waiting' | 'running' | 'saved' | 'kept' | 'no_delivery' | 'holiday' | 'failed'

interface DayProgress {
  key: WeekDayKey
  outcome: DayOutcome
  note: string
}

const OUTCOME_TEXT: Record<DayOutcome, string> = {
  waiting: 'Waiting',
  running: 'Running…',
  saved: 'Saved',
  kept: 'Kept the saved forecast',
  no_delivery: 'No deliveries',
  holiday: 'Bank holiday, skipped',
  failed: 'Failed',
}

const OUTCOME_CLASS: Record<DayOutcome, string> = {
  waiting: 'text-muted-foreground',
  running: 'text-foreground',
  saved: 'text-good-text',
  kept: 'text-muted-foreground',
  no_delivery: 'text-muted-foreground',
  holiday: 'text-warning',
  failed: 'text-critical',
}

interface WholeWeekDialogProps {
  open: boolean
  onClose: () => void
  weekKey: WeekDayKey
  model: string
  modelLabel: string
  /** Called once every day has been handled, so the page can reload what is saved. */
  onFinished: () => void
}

/** Runs and saves the forecast of every delivery day of one ISO week, one day at a time. */
export function WholeWeekDialog({
  open,
  onClose,
  weekKey,
  model,
  modelLabel,
  onFinished,
}: WholeWeekDialogProps) {
  const weekDays = daysOfWeek(weekKey)
  const firstDate = deliveryDateFromKey(weekDays[0])
  const lastDate = deliveryDateFromKey(weekDays[weekDays.length - 1])
  const firstYearHolidays = useBankHolidays(Number(firstDate.slice(0, 4)))
  const lastYearHolidays = useBankHolidays(Number(lastDate.slice(0, 4)))
  const [overwriteSaved, setOverwriteSaved] = React.useState(false)
  const [skipBankHolidays, setSkipBankHolidays] = React.useState(true)
  const [progress, setProgress] = React.useState<DayProgress[]>([])
  const [isRunning, setIsRunning] = React.useState(false)

  const holidayLabelByDate = new Map<string, string>()
  const weekHolidays = [...(firstYearHolidays.data ?? []), ...(lastYearHolidays.data ?? [])]
  for (const holiday of weekHolidays) holidayLabelByDate.set(holiday.holiday_date, holiday.label)

  const isFinished = progress.length > 0 && !isRunning
  const holidaysLoaded = firstYearHolidays.isSuccess && lastYearHolidays.isSuccess

  function close() {
    if (isRunning) return
    setProgress([])
    onClose()
  }

  function markDay(index: number, outcome: DayOutcome, note = '') {
    setProgress((current) =>
      current.map((day, dayIndex) => (dayIndex === index ? { ...day, outcome, note } : day)),
    )
  }

  async function forecastWholeWeek() {
    setIsRunning(true)
    setProgress(weekDays.map((key) => ({ key, outcome: 'waiting', note: '' })))
    for (const [index, dayKey] of weekDays.entries()) {
      const deliveryDate = deliveryDateFromKey(dayKey)
      const holidayLabel = holidayLabelByDate.get(deliveryDate)
      if (skipBankHolidays && holidayLabel !== undefined) {
        markDay(index, 'holiday', holidayLabel)
        continue
      }
      markDay(index, 'running')
      const result = await forecastAndSaveDay(deliveryDate, model, overwriteSaved)
      markDay(index, result.outcome, result.note)
    }
    setIsRunning(false)
    onFinished()
  }

  const summary = summarizeProgress(progress)

  return (
    <Modal
      open={open}
      onClose={close}
      title={`Forecast whole week ${weekKey.year} · ${weekLabel(weekKey)}`}
      description={`Runs "${modelLabel}" for every day of the week that has deliveries, then saves it.`}
      footer={
        <>
          <Button variant="outline" onClick={close} disabled={isRunning}>
            {isFinished ? 'Close' : 'Cancel'}
          </Button>
          {!isFinished && (
            <Button onClick={forecastWholeWeek} disabled={isRunning || !holidaysLoaded}>
              {isRunning ? 'Working…' : 'Forecast week'}
            </Button>
          )}
        </>
      }
    >
      {progress.length === 0 && (
        <div className="space-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={overwriteSaved}
              onChange={(event) => setOverwriteSaved(event.target.checked)}
            />
            Overwrite days that already have a saved forecast
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={skipBankHolidays}
              onChange={(event) => setSkipBankHolidays(event.target.checked)}
            />
            Skip bank holidays (no delivery on those days)
          </label>
        </div>
      )}
      {progress.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {progress.map((day) => (
            <li key={day.key.dayName} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span>{day.key.dayName}</span>
              <span className={OUTCOME_CLASS[day.outcome]} title={day.note || undefined}>
                {OUTCOME_TEXT[day.outcome]}
                {day.note && ` (${day.note})`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {isFinished && <p className="text-sm font-medium">{summary}</p>}
    </Modal>
  )
}

interface DayResult {
  outcome: DayOutcome
  note: string
}

async function forecastAndSaveDay(
  deliveryDate: string,
  model: string,
  overwrite: boolean,
): Promise<DayResult> {
  try {
    const run = await api.post<ForecastRun>('/api/v1/forecasts/run', {
      delivery_date: deliveryDate,
      model,
    })
    const body: ForecastSaveRequest = {
      run_id: run.run_id,
      cells: cellsFromDraft(run, draftFromRun(run)),
      overwrite,
    }
    await api.post<ForecastRun>('/api/v1/forecasts/save', body)
    return { outcome: 'saved', note: '' }
  } catch (error) {
    return outcomeForError(error)
  }
}

function outcomeForError(error: unknown): DayResult {
  if (!(error instanceof ApiError)) return { outcome: 'failed', note: 'unexpected error' }
  if (error.code === 'no_delivery_config') return { outcome: 'no_delivery', note: '' }
  if (error.code === 'exists') return { outcome: 'kept', note: '' }
  return { outcome: 'failed', note: error.message }
}

function summarizeProgress(progress: DayProgress[]): string {
  const countOf = (outcome: DayOutcome) => progress.filter((day) => day.outcome === outcome).length
  const parts = [
    `${countOf('saved')} saved`,
    `${countOf('kept')} kept`,
    `${countOf('holiday')} bank holiday`,
    `${countOf('no_delivery')} without deliveries`,
    `${countOf('failed')} failed`,
  ]
  return parts.join(' · ')
}
