/** Formatting helpers shared across pages. */

const EUR_FORMATTER = new Intl.NumberFormat('nl-BE', {
  style: 'currency',
  currency: 'EUR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/**
 * Format a decimal string (as the backend returns money, e.g. "2.45") or a
 * number into a euro-formatted string. Returns an em dash for null/blank input.
 */
export function formatEuro(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) return '—'
  return EUR_FORMATTER.format(numeric)
}

/** Format an ISO datetime string as a short locale date-time; em dash if empty. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
