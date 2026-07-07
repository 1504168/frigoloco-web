/** Finance-local formatting + numeric helpers (money stays as euro strings). */

import { API_BASE_URL } from '@/lib/api'

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

/** Format a fraction (e.g. 0.272) as a percent string, or em dash for null. */
export function formatPercent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return '—'
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

/** Pull the filename out of a Content-Disposition header, if present. */
function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const utf8 = header.match(/filename\*=(?:UTF-8'')?["']?([^"';]+)/i)
  if (utf8?.[1]) return decodeURIComponent(utf8[1])
  const plain = header.match(/filename=["']?([^"';]+)/i)
  return plain?.[1] ?? null
}

/**
 * Fetch a file endpoint and trigger a browser download via an object URL,
 * honoring the server's Content-Disposition filename. Throws on non-2xx so the
 * caller can surface an error toast.
 */
export async function downloadFileFromApi(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { Accept: '*/*' } })
  if (!response.ok) {
    throw new Error(`Export failed (${response.status})`)
  }
  const blob = await response.blob()
  const filename = filenameFromDisposition(response.headers.get('Content-Disposition')) ?? fallbackName
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(objectUrl)
}
