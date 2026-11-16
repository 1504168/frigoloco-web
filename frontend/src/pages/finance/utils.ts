/** Finance-local formatting + numeric helpers (money stays as euro strings). */

import { EMPTY_PLACEHOLDER } from '@/lib/format'

const PERCENT_FORMATTER = new Intl.NumberFormat('nl-BE', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

const INT_FORMATTER = new Intl.NumberFormat('nl-BE', { maximumFractionDigits: 0 })

/** Parse a decimal-euro string to a number; NaN-safe, treats null/blank as 0. */
export function toNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0
  const numeric = typeof value === 'number' ? value : Number(value)
  return Number.isNaN(numeric) ? 0 : numeric
}

/** Format a fraction (e.g. 0.272) as a percent string, or the placeholder for null. */
export function formatPercent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return EMPTY_PLACEHOLDER
  return PERCENT_FORMATTER.format(fraction)
}

/** Ratio numerator/denominator as a fraction; null when denominator is ~0. */
export function safeRatio(numerator: number, denominator: number): number | null {
  if (!denominator) return null
  return numerator / denominator
}

/** Format an integer count. */
export function formatCount(value: number): string {
  return INT_FORMATTER.format(value)
}

/** Sum the numeric value of a euro-string field across rows. */
export function sumField<T>(rows: T[], accessor: (row: T) => string | null | undefined): number {
  return rows.reduce((total, row) => total + toNumber(accessor(row)), 0)
}
