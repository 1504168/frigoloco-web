/**
 * The calendar date the user sees on their own clock, as YYYY-MM-DD.
 * `toISOString()` gives the UTC date instead, which is yesterday or tomorrow
 * for part of every day outside UTC.
 */
export function localIsoDate(date: Date = new Date()): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Local calendar date `days` days from today, as YYYY-MM-DD. */
export function localIsoDatePlusDays(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return localIsoDate(date)
}
