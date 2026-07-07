/**
 * ISO-8601 week helpers. The backend keys weekly P&L on (year, iso_week), so
 * the 9-week trend chart must walk consecutive ISO weeks backwards from the
 * selected week. All arithmetic is done in UTC to avoid DST/off-by-one drift.
 */

/** A concrete ISO week identity. */
export interface IsoWeek {
  year: number
  week: number
}

const MS_PER_DAY = 86_400_000

/** Monday 00:00 UTC of the given ISO week. */
export function isoWeekToMonday(year: number, week: number): Date {
  // Jan 4th is always in ISO week 1. Find the Monday of week 1, then add weeks.
  const jan4 = new Date(Date.UTC(year, 0, 4))
  const jan4Dow = jan4.getUTCDay() || 7 // Sunday(0) -> 7
  const week1Monday = new Date(jan4.getTime() - (jan4Dow - 1) * MS_PER_DAY)
  return new Date(week1Monday.getTime() + (week - 1) * 7 * MS_PER_DAY)
}

/** ISO (year, week) that a given UTC date falls into. */
export function dateToIsoWeek(date: Date): IsoWeek {
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()))
  const dow = target.getUTCDay() || 7
  // Shift to the Thursday of this week — its calendar year is the ISO year.
  target.setUTCDate(target.getUTCDate() + 4 - dow)
  const isoYear = target.getUTCFullYear()
  const yearStart = new Date(Date.UTC(isoYear, 0, 1))
  const week = Math.ceil(((target.getTime() - yearStart.getTime()) / MS_PER_DAY + 1) / 7)
  return { year: isoYear, week }
}

/** The `count` ISO weeks ending at (and including) the given week, oldest first. */
export function recentIsoWeeks(year: number, week: number, count: number): IsoWeek[] {
  const anchorMonday = isoWeekToMonday(year, week)
  const weeks: IsoWeek[] = []
  for (let offset = count - 1; offset >= 0; offset -= 1) {
    const monday = new Date(anchorMonday.getTime() - offset * 7 * MS_PER_DAY)
    weeks.push(dateToIsoWeek(monday))
  }
  return weeks
}

/** Number of ISO weeks (52 or 53) in a given ISO year. */
export function isoWeeksInYear(year: number): number {
  const dec28 = new Date(Date.UTC(year, 11, 28))
  return dateToIsoWeek(dec28).week
}

/** Short human label for an ISO week, e.g. "W26 · 22–28 Jun 2026". */
export function formatIsoWeekRange(year: number, week: number): string {
  const monday = isoWeekToMonday(year, week)
  const sunday = new Date(monday.getTime() + 6 * MS_PER_DAY)
  const dayMonth = (d: Date, withMonth: boolean) =>
    d.toLocaleDateString('en-GB', {
      day: '2-digit',
      month: withMonth ? 'short' : undefined,
      year: undefined,
      timeZone: 'UTC',
    })
  const sameMonth = monday.getUTCMonth() === sunday.getUTCMonth()
  const start = dayMonth(monday, !sameMonth)
  const end = sunday.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
  return `W${week} · ${start}–${end}`
}
