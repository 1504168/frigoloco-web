/** Formatting helpers shared across pages. */

import type { Fridge } from '@/lib/types'

const EUR_FORMATTER = new Intl.NumberFormat('nl-BE', {
  style: 'currency',
  currency: 'EUR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Rendered wherever a value is null, blank or unparseable. */
export const EMPTY_PLACEHOLDER = '-'

/**
 * Format a decimal string (as the backend returns money, e.g. "2.45") or a
 * number into a euro-formatted string. Returns the empty placeholder for
 * null/blank input.
 */
export function formatEuro(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return EMPTY_PLACEHOLDER
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) return EMPTY_PLACEHOLDER
  return EUR_FORMATTER.format(numeric)
}

/**
 * Format a 0..1 fraction string (or number) as a percent: "0.8571" -> "85.7%".
 * Every ratio the backend returns (vat_rate, pos_fee_pct, pct_sold,
 * profit_margin, margin_pct) is a fraction, never percent units.
 *
 * `fractionDigits` pins the number of decimals; when omitted, whole percents
 * render without decimals and the rest with one. Returns the empty placeholder
 * for null/blank/unparseable input.
 */
export function formatFraction(
  value: string | number | null | undefined,
  fractionDigits?: number,
): string {
  if (value === null || value === undefined || value === '') return EMPTY_PLACEHOLDER
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) return EMPTY_PLACEHOLDER
  const percent = numeric * 100
  const digits = fractionDigits ?? (percent % 1 === 0 ? 0 : 1)
  return `${percent.toFixed(digits)}%`
}

/**
 * Display label for a fridge: the friendly name, falling back to the Husky name
 * (nullable on FridgeRead) and finally to the id, so a lookup never renders blank.
 */
export function formatFridgeName(
  fridge: Pick<Fridge, 'id' | 'friendly_name' | 'husky_name'>,
): string {
  return fridge.friendly_name || fridge.husky_name || `Fridge #${fridge.id}`
}

/** Format an ISO datetime string as a short locale date-time; placeholder if empty. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return EMPTY_PLACEHOLDER
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return EMPTY_PLACEHOLDER
  return date.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
