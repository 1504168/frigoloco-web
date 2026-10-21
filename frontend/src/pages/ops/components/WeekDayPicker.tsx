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

/** ISO weeks 1-53. */
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

/** Select widths for the roomy (default) and compact toolbar layouts. */
const PICKER_SIZES = {
  regular: {
    wrapper: 'gap-2 rounded-lg border border-border bg-card px-3 py-2',
    trigger: 'h-8',
    year: 'w-[92px]',
    week: 'w-[92px]',
    day: 'w-[128px]',
  },
  compact: {
    wrapper: 'gap-1.5',
    trigger: 'h-9',
    // Tighter padding keeps '2026' and 'W43' unclipped at the narrow compact widths.
    year: 'w-20 px-2',
    week: 'w-[72px] px-2',
    day: 'w-32',
  },
} as const

/** Compact day label, e.g. "Fri 10 Jul", so the delivery date needs no extra toolbar width. */
const COMPACT_DAY_LABEL_FORMAT = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
})

export interface WeekDayPickerProps {
  value: WeekDayKey
  onChange: (next: WeekDayKey) => void
  /** When set, renders pills linking to the other two stages, preserving the key. */
  showStageNav?: boolean
  /** One-row layout: narrow selects, delivery date shown in the day select, no stage pills. */
  compact?: boolean
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
  // Stage navigation is off by default: the left nav already switches between
  // Forecast/Menu/Dispatch. Opt back in per page if key-preserving tabs are wanted.
  showStageNav = false,
  compact = false,
  className,
}: WeekDayPickerProps) {
  const sizes = compact ? PICKER_SIZES.compact : PICKER_SIZES.regular
  const isStageNavVisible = showStageNav && !compact
  const deliveryDate = deliveryDateFromKey(value)
  const deliveryLabel = `Delivery ${deliveryDate}`
  const compactDayLabel = COMPACT_DAY_LABEL_FORMAT.format(new Date(deliveryDate))
  const stageQuery = `?year=${value.year}&week=${value.week}&day=${value.dayName}`

  return (
    <div className={cn('flex flex-wrap items-center gap-3', className)}>
      <div className={cn('flex items-center', sizes.wrapper)}>
        <CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground" />
        <label className="sr-only" htmlFor="wdp-year">
          Year
        </label>
        <Select
          value={String(value.year)}
          onValueChange={(next) => onChange({ ...value, year: Number(next) })}
        >
          <SelectTrigger id="wdp-year" className={cn(sizes.trigger, sizes.year)}>
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
          <SelectTrigger id="wdp-week" className={cn(sizes.trigger, sizes.week)}>
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
          <SelectTrigger
            id="wdp-day"
            className={cn(sizes.trigger, sizes.day)}
            title={deliveryLabel}
          >
            <SelectValue>{compact ? compactDayLabel : undefined}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {DAY_NAMES.map((day) => (
              <SelectItem key={day} value={day}>
                {day}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {compact ? null : (
          <span className="hidden whitespace-nowrap pl-1 text-xs text-muted-foreground sm:inline">
            {deliveryLabel}
          </span>
        )}
      </div>

      {isStageNavVisible ? (
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
