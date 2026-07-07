/** Helpers for the monthly "YYYY-MM" picker and compare selector. */

/** Current month as "YYYY-MM" (UTC). */
export function currentMonthKey(): string {
  const now = new Date()
  return `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`
}

/** Shift a "YYYY-MM" key by `delta` months (can be negative). */
export function shiftMonth(monthKey: string, delta: number): string {
  const [year, month] = monthKey.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1 + delta, 1))
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
}

/** "June 2026" from "2026-06". */
export function formatMonthLabel(monthKey: string): string {
  const [year, month] = monthKey.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString('en-GB', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/** The most recent `count` month keys, newest first, ending at `end`. */
export function recentMonths(end: string, count: number): string[] {
  return Array.from({ length: count }, (_, index) => shiftMonth(end, -index))
}
