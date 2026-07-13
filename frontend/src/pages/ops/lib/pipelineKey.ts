/**
 * The FrigoLoco Forecast → Menu → Dispatch pipeline keys every stage on the
 * triple (iso_year, week_no, day_name). This module is the single source of
 * truth for that key: its type, ISO-week ↔ calendar-date conversions, and the
 * URL-search-param binding that keeps the three pages in sync as the operator
 * navigates between them.
 */
import * as React from 'react'
import { useSearchParams } from 'react-router-dom'

/** Ordered ISO day names; index + 1 is the ISO weekday (Monday = 1 … Sunday = 7). */
export const DAY_NAMES = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
] as const

export type DayName = (typeof DAY_NAMES)[number]

/** The pipeline key shared by Forecast, Menu and Dispatch. */
export interface WeekDayKey {
  year: number
  week: number
  dayName: DayName
}

/** ISO weekday (1–7) for a day name; defaults to Monday for unknown input. */
export function dayNumber(dayName: DayName): number {
  const index = DAY_NAMES.indexOf(dayName)
  return index === -1 ? 1 : index + 1
}

/** Zero-padded ISO week label, e.g. "2027 · W02". */
export function weekKeyLabel(key: WeekDayKey): string {
  return `${key.year} · W${String(key.week).padStart(2, '0')} · ${key.dayName}`
}

/**
 * Calendar date (yyyy-mm-dd) for an ISO year/week/weekday. Mirrors Python's
 * `date.fromisocalendar` so the delivery date the frontend sends matches the
 * backend's key derivation exactly. All math is in UTC to avoid DST drift.
 */
export function deliveryDateFromKey(key: WeekDayKey): string {
  const weekday = dayNumber(key.dayName)
  // Jan 4th is always in ISO week 1; walk back to that week's Monday.
  const jan4 = new Date(Date.UTC(key.year, 0, 4))
  const jan4Weekday = jan4.getUTCDay() || 7 // getUTCDay: Sun = 0 → 7
  const week1Monday = new Date(jan4)
  week1Monday.setUTCDate(jan4.getUTCDate() - (jan4Weekday - 1))
  const target = new Date(week1Monday)
  target.setUTCDate(week1Monday.getUTCDate() + (key.week - 1) * 7 + (weekday - 1))
  return target.toISOString().slice(0, 10)
}

/** ISO year/week/weekday for a given Date (defaults to today). */
export function currentWeekDayKey(reference: Date = new Date()): WeekDayKey {
  // Copy at UTC midnight so weekday math is stable.
  const date = new Date(Date.UTC(reference.getFullYear(), reference.getMonth(), reference.getDate()))
  const weekday = date.getUTCDay() || 7
  // Shift to the Thursday of this week - the ISO year owner of the week.
  const thursday = new Date(date)
  thursday.setUTCDate(date.getUTCDate() + (4 - weekday))
  const isoYear = thursday.getUTCFullYear()
  const week1Thursday = new Date(Date.UTC(isoYear, 0, 4))
  const week1Weekday = week1Thursday.getUTCDay() || 7
  week1Thursday.setUTCDate(week1Thursday.getUTCDate() + (4 - week1Weekday))
  const week = 1 + Math.round((thursday.getTime() - week1Thursday.getTime()) / (7 * 86_400_000))
  return { year: isoYear, week, dayName: DAY_NAMES[weekday - 1] }
}

/** True when the key's delivery date is strictly before today (needs force to dispatch). */
export function keyIsPast(key: WeekDayKey): boolean {
  return deliveryDateFromKey(key) < new Date().toISOString().slice(0, 10)
}

const STORAGE_KEY = 'ops.weekDayKey'

function normalizeDayName(raw: string | null): DayName | null {
  if (!raw) return null
  const match = DAY_NAMES.find((day) => day.toLowerCase() === raw.toLowerCase())
  return match ?? null
}

/** Read a persisted key from sessionStorage (used when the URL carries none). */
function readStoredKey(): WeekDayKey | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<WeekDayKey>
    const dayName = normalizeDayName(parsed.dayName ?? null)
    if (!parsed.year || !parsed.week || !dayName) return null
    return { year: Number(parsed.year), week: Number(parsed.week), dayName }
  } catch {
    return null
  }
}

/**
 * Binds the pipeline key to `?year&week&day` URL search params, falling back to
 * the last selection (sessionStorage) and finally the current ISO week. Writing
 * a new key updates both the URL and storage so a sibling page - reached via the
 * sidebar without params - restores the same selection.
 */
export function useWeekDayKey(): { key: WeekDayKey; setKey: (next: WeekDayKey) => void } {
  const [searchParams, setSearchParams] = useSearchParams()

  const key = React.useMemo<WeekDayKey>(() => {
    const yearParam = Number(searchParams.get('year'))
    const weekParam = Number(searchParams.get('week'))
    const dayParam = normalizeDayName(searchParams.get('day'))
    if (yearParam && weekParam && dayParam) {
      return { year: yearParam, week: weekParam, dayName: dayParam }
    }
    return readStoredKey() ?? currentWeekDayKey()
  }, [searchParams])

  // Ensure the URL always reflects the resolved key (so links/refresh are stable).
  React.useEffect(() => {
    const hasParams =
      searchParams.get('year') && searchParams.get('week') && searchParams.get('day')
    if (!hasParams) {
      const next = new URLSearchParams(searchParams)
      next.set('year', String(key.year))
      next.set('week', String(key.week))
      next.set('day', key.dayName)
      setSearchParams(next, { replace: true })
    }
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(key))
  }, [key, searchParams, setSearchParams])

  const setKey = React.useCallback(
    (next: WeekDayKey) => {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      const params = new URLSearchParams(searchParams)
      params.set('year', String(next.year))
      params.set('week', String(next.week))
      params.set('day', next.dayName)
      setSearchParams(params, { replace: false })
    },
    [searchParams, setSearchParams],
  )

  return { key, setKey }
}
