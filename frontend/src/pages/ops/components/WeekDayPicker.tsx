import { NavLink } from 'react-router-dom'
import { CalendarDays } from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import {
  DAY_NAMES,
  deliveryDateFromKey,
  type DayName,
  type WeekDayKey,
} from '@/pages/ops/lib/pipelineKey'

/** ISO weeks 1–53. */
const WEEK_OPTIONS = Array.from({ length: 53 }, (_, index) => index + 1)

/** A small span of selectable years around the current one. */
function yearOptions(selected: number): number[] {
  const base = new Date().getFullYear()
  const years = new Set<number>([selected])
  for (let year = base - 2; year <= base + 3; year += 1) years.add(year)
  return Array.from(years).sort((a, b) => a - b)
}

/** The three pipeline stages, used for the sync-preserving nav pills. */
const STAGES = [
  { path: '/forecast', label: 'Forecast' },
  { path: '/menu', label: 'Menu' },
  { path: '/dispatch', label: 'Dispatch' },
] as const

export interface WeekDayPickerProps {
  value: WeekDayKey
  onChange: (next: WeekDayKey) => void
  /** When set, renders pills linking to the other two stages, preserving the key. */
  showStageNav?: boolean
  className?: string
}

/**
 * Year + ISO-week + day-of-week selector that drives the Forecast/Menu/Dispatch
 * pages. The selection lives in the URL (see `useWeekDayKey`); this component is
 * a controlled view of that key plus stage-navigation pills that carry the key
 * across pages so the three stages stay in sync.
 */
export function WeekDayPicker({
  value,
  onChange,
  showStageNav = true,
  className,
}: WeekDayPickerProps) {
  const deliveryDate = deliveryDateFromKey(value)
  const stageQuery = `?year=${value.year}&week=${value.week}&day=${value.dayName}`

  return (
    <div className={cn('flex flex-wrap items-center gap-3', className)}>
      <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2">
        <CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground" />
        <label className="sr-only" htmlFor="wdp-year">
          Year
        </label>
        <Select
          value={String(value.year)}
          onValueChange={(next) => onChange({ ...value, year: Number(next) })}
        >
          <SelectTrigger id="wdp-year" className="h-8 w-[92px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {yearOptions(value.year).map((year) => (
              <SelectItem key={year} value={String(year)}>
                {year}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <label className="sr-only" htmlFor="wdp-week">
          ISO week
        </label>
        <Select
          value={String(value.week)}
          onValueChange={(next) => onChange({ ...value, week: Number(next) })}
        >
          <SelectTrigger id="wdp-week" className="h-8 w-[92px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {WEEK_OPTIONS.map((week) => (
              <SelectItem key={week} value={String(week)}>
                W{String(week).padStart(2, '0')}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <label className="sr-only" htmlFor="wdp-day">
          Day of week
        </label>
        <Select
          value={value.dayName}
          onValueChange={(next) => onChange({ ...value, dayName: next as DayName })}
        >
          <SelectTrigger id="wdp-day" className="h-8 w-[128px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DAY_NAMES.map((day) => (
              <SelectItem key={day} value={day}>
                {day}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <span className="hidden whitespace-nowrap pl-1 text-xs text-muted-foreground sm:inline">
          Delivery {deliveryDate}
        </span>
      </div>

      {showStageNav ? (
        <nav className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-1">
          {STAGES.map((stage) => (
            <NavLink
              key={stage.path}
              to={`${stage.path}${stageQuery}`}
              className={({ isActive }) =>
                cn(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  isActive
                    ? 'bg-card text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                )
              }
            >
              {stage.label}
            </NavLink>
          ))}
        </nav>
      ) : null}
    </div>
  )
}
