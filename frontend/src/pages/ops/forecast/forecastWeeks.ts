/**
 * ISO-week and calendar-day helpers for the Forecast page: sales-window labels,
 * "Compare with" windows and the days of a whole week.
 * Every date is a yyyy-mm-dd string; the math runs in UTC so DST never shifts a day.
 */
import {
  currentWeekDayKey,
  DAY_NAMES,
  deliveryDateFromKey,
  type DayName,
  type WeekDayKey,
} from '@/pages/ops/lib/pipelineKey'

const DAY_MS = 86_400_000
const SHORT_DATE_FMT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
})
const DAYS_PER_WEEK = 7
const MONDAY_TO_FRIDAY = [1, 2, 3, 4, 5]
/** Below a week there is nothing to average: such windows always show totals. */
const MIN_WEEKS_TO_AVERAGE = 1
/** How many earlier weeks the "Compare with" week picker offers. */
const COMPARE_WEEK_CHOICES = 12

export type CompareChoice = 'none' | 'same_weekday' | 'monday_to_friday' | 'custom'

/** What the "Compare with" picker holds; the window is derived from it and the page key. */
export interface CompareSelection {
  choice: CompareChoice
  /** For the week presets: how many weeks before the selected week. */
  weeksBack: number
  /** For the custom range: first and last day, both inclusive (yyyy-mm-dd or ''). */
  firstDay: string
  lastDay: string
}

export const NO_COMPARE: CompareSelection = {
  choice: 'none',
  weeksBack: 1,
  firstDay: '',
  lastDay: '',
}

/** A window of actuals: `start` inclusive, `end` exclusive, optional ISO weekday filter. */
export interface ActualsWindow {
  start: string
  end: string
  weekdays: number[] | null
  label: string
}

/** One ISO week the user can compare against. */
export interface IsoWeek {
  year: number
  week: number
}

export function addDays(isoDate: string, days: number): string {
  const day = new Date(`${isoDate}T00:00:00Z`)
  return new Date(day.getTime() + days * DAY_MS).toISOString().slice(0, 10)
}

export function daysBetween(start: string, end: string): number {
  const startMs = new Date(`${start}T00:00:00Z`).getTime()
  const endMs = new Date(`${end}T00:00:00Z`).getTime()
  return Math.round((endMs - startMs) / DAY_MS)
}

export function isoWeekOf(isoDate: string): IsoWeek {
  const [year, month, day] = isoDate.split('-').map(Number)
  const key = currentWeekDayKey(new Date(year, month - 1, day))
  return { year: key.year, week: key.week }
}

export function weekLabel(week: IsoWeek): string {
  return `W${String(week.week).padStart(2, '0')}`
}

/** "W47-W50 (21 days)" for a window from `start` to the exclusive `end`. */
export function windowWeeksLabel(start: string, end: string): string {
  const days = daysBetween(start, end)
  const firstWeek = weekLabel(isoWeekOf(start))
  const lastWeek = weekLabel(isoWeekOf(addDays(end, -1)))
  const weeks = firstWeek === lastWeek ? firstWeek : `${firstWeek}-${lastWeek}`
  const dayWord = days === 1 ? 'day' : 'days'
  return `${weeks} (${days} ${dayWord})`
}

/** The divisor of the "per week average" view: window weeks, never below one week. */
export function perWeekDivisor(start: string, end: string): number {
  const weeks = daysBetween(start, end) / DAYS_PER_WEEK
  return Math.max(weeks, MIN_WEEKS_TO_AVERAGE)
}

/** The ISO week `weeksBack` weeks before `key`'s week. */
export function isoWeekBefore(key: WeekDayKey, weeksBack: number): IsoWeek {
  const mondayOfKey = deliveryDateFromKey({ ...key, dayName: 'Monday' })
  return isoWeekOf(addDays(mondayOfKey, -weeksBack * DAYS_PER_WEEK))
}

/** 1, 2, ... weeks back: the choices of the compare week picker. */
export const COMPARE_WEEKS_BACK = Array.from({ length: COMPARE_WEEK_CHOICES }, (_, i) => i + 1)

/** The actuals window a compare selection stands for; null when there is none (yet). */
export function compareWindowFor(
  selection: CompareSelection,
  key: WeekDayKey,
): ActualsWindow | null {
  if (selection.choice === 'none') return null
  if (selection.choice === 'custom') return customWindow(selection.firstDay, selection.lastDay)
  const compareWeek = isoWeekBefore(key, selection.weeksBack)
  return presetWindow(selection.choice, compareWeek, key.dayName)
}

function presetWindow(
  preset: 'same_weekday' | 'monday_to_friday',
  compareWeek: IsoWeek,
  dayName: DayName,
): ActualsWindow {
  if (preset === 'same_weekday') {
    const start = deliveryDateFromKey({ ...compareWeek, dayName })
    return {
      start,
      end: addDays(start, 1),
      weekdays: null,
      label: `${dayName.slice(0, 3)} ${weekLabel(compareWeek)}`,
    }
  }
  const monday = deliveryDateFromKey({ ...compareWeek, dayName: 'Monday' })
  return {
    start: monday,
    end: addDays(monday, DAYS_PER_WEEK),
    weekdays: MONDAY_TO_FRIDAY,
    label: `Mon-Fri ${weekLabel(compareWeek)}`,
  }
}

/** A custom window from the first to the last day the user picked (both inclusive). */
function customWindow(firstDay: string, lastDay: string): ActualsWindow | null {
  if (firstDay === '' || lastDay === '' || lastDay < firstDay) return null
  const end = addDays(lastDay, 1)
  const label = `${shortDate(firstDay)} - ${shortDate(lastDay)}, ${windowWeeksLabel(firstDay, end)}`
  return { start: firstDay, end, weekdays: null, label }
}

/** "20 Oct" for an ISO date. */
function shortDate(isoDate: string): string {
  return SHORT_DATE_FMT.format(new Date(`${isoDate}T00:00:00Z`))
}

/** The custom range offered when "Custom range" is picked: the week before the delivery. */
export function defaultCustomRange(key: WeekDayKey): { firstDay: string; lastDay: string } {
  const deliveryDate = deliveryDateFromKey(key)
  return {
    firstDay: addDays(deliveryDate, -DAYS_PER_WEEK),
    lastDay: addDays(deliveryDate, -1),
  }
}

/** Every day of `key`'s ISO week, Monday first. */
export function daysOfWeek(key: WeekDayKey): WeekDayKey[] {
  return DAY_NAMES.map((dayName) => ({ year: key.year, week: key.week, dayName }))
}
