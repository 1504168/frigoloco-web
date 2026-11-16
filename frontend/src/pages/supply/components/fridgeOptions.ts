/** Select value for fridges that have no client yet. */
export const NO_CLIENT_VALUE = 'none'

/**
 * Weekday labels by row index. The API uses ISO weekday numbers (Mon=1 … Sun=7),
 * so the integer sent/received is always `index + 1`.
 */
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const DAYS_PER_WEEK = 7
const SATURDAY_ISO = 6
const SUNDAY_ISO = 7
/** Shown for a fridge the catalogue sync has not stamped with a Husky status yet. */
const UNKNOWN_HUSKY_STATUS_LABEL = 'Not synced'

/** "READY_TO_USE" -> "Ready to use". */
export function huskyStatusLabel(huskyStatus: string | null): string {
  if (huskyStatus === null) return UNKNOWN_HUSKY_STATUS_LABEL
  const words = huskyStatus.replaceAll('_', ' ').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * Selling days among the `calendarDays` days starting on ISO `weekday`. A fridge
 * closed on weekends sells nothing on Saturday and Sunday. Mirrors
 * count_selling_days in the backend forecast_service.py.
 */
export function countSellingDays(
  weekday: number,
  calendarDays: number,
  activeOnWeekends: boolean,
): number {
  if (activeOnWeekends) return calendarDays
  let sellingDays = 0
  for (let offset = 0; offset < calendarDays; offset++) {
    const coveredWeekday = ((weekday - 1 + offset) % DAYS_PER_WEEK) + 1
    const isWeekend = coveredWeekday === SATURDAY_ISO || coveredWeekday === SUNDAY_ISO
    if (!isWeekend) sellingDays++
  }
  return sellingDays
}
