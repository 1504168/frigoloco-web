import type { ReactNode } from 'react'
import { AlertTriangle, Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ForecastRun } from '@/pages/ops/lib/types'

const DAY_FMT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})
const DAY_MS = 86_400_000

type NoticeTone = 'warning' | 'info'

const NOTICE_STYLES: Record<NoticeTone, { icon: typeof Info; role: string; className: string }> = {
  warning: {
    icon: AlertTriangle,
    role: 'alert',
    className: 'border-warning/50 bg-warning/10 text-foreground',
  },
  info: {
    icon: Info,
    role: 'status',
    className: 'border-border bg-muted/40 text-muted-foreground',
  },
}

interface ForecastNoticesProps {
  run: ForecastRun
  modelLabel: string
  /** Grid view toggles shown at the right end of the run facts line. */
  viewOptions: ReactNode
}

/** Run facts above the grid: method, sales window, saved state, and data warnings. */
export function ForecastNotices({ run, modelLabel, viewOptions }: ForecastNoticesProps) {
  const firstDay = formatDay(run.window_start)
  const lastDay = formatDay(dayBefore(run.window_end))
  const hasNoSales = run.window_sales_units === 0
  const excludedHolidays = (run.params.excluded_bank_holidays ?? []).map(formatDay)
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {modelLabel} · sales from {firstDay} to {lastDay} ·{' '}
          <span className="font-medium text-foreground">
            {run.is_saved ? 'Saved' : 'Not saved'}
          </span>
        </p>
        {viewOptions}
      </div>
      {run.delivery_bank_holiday !== null && (
        <Notice tone="warning">
          The delivery day is a bank holiday ({run.delivery_bank_holiday}).
        </Notice>
      )}
      {excludedHolidays.length > 0 && (
        <Notice tone="info">
          Bank holidays left out of the selling days: {excludedHolidays.join(', ')}.
        </Notice>
      )}
      {hasNoSales && (
        <Notice tone="warning">
          No sales recorded between {firstDay} and {lastDay}.
        </Notice>
      )}
      {!run.residual_applied && (
        <Notice tone="info">Residual stock not applied: only current stock is known.</Notice>
      )}
    </div>
  )
}

function Notice({ tone, children }: { tone: NoticeTone; children: ReactNode }) {
  const style = NOTICE_STYLES[tone]
  return (
    <div
      role={style.role}
      className={cn('flex items-center gap-2 rounded-lg border px-3 py-2 text-xs', style.className)}
    >
      <style.icon className="h-4 w-4 shrink-0" />
      <span>{children}</span>
    </div>
  )
}

function formatDay(isoDate: string): string {
  return DAY_FMT.format(new Date(`${isoDate}T00:00:00Z`))
}

function dayBefore(isoDate: string): string {
  const day = new Date(`${isoDate}T00:00:00Z`)
  return new Date(day.getTime() - DAY_MS).toISOString().slice(0, 10)
}
