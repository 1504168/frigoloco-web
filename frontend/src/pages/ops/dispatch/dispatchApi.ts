import { api, API_BASE_URL } from '@/lib/api'
import { getToken } from '@/lib/auth'
import type { WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import type { DispatchMatrix, DispatchRead, GridLineItem } from '@/pages/ops/lib/types'

/** GET /dispatches/{id}/matrix: the grid plus the cost at snapshot prices once dispatched. */
export interface SavedDispatchMatrix extends DispatchMatrix {
  dispatched_cost_total: string | null
}

export interface SavedDispatch {
  saved: DispatchRead
  matrix: SavedDispatchMatrix
}

/** Query key prefix of every cached dispatch read; invalidate it after a write. */
export const DISPATCH_QUERY_KEY = ['ops', 'dispatch'] as const

type QuantityLine = Pick<GridLineItem, 'fridge_id' | 'product_id' | 'qty'>

/** Load the saved dispatch for a key with its matrix; throws ApiError 404 when none. */
export async function fetchSavedDispatch(
  key: WeekDayKey,
  signal?: AbortSignal,
): Promise<SavedDispatch> {
  const saved = await api.get<DispatchRead>('/api/v1/dispatches/saved', {
    params: { year: key.year, week: key.week, day_name: key.dayName },
    signal,
  })
  const matrix = await api.get<SavedDispatchMatrix>(`/api/v1/dispatches/${saved.id}/matrix`, {
    signal,
  })
  return { saved, matrix }
}

/**
 * Order-independent fingerprint of the planned quantities, so the grid on
 * screen can be compared with what is saved.
 */
export function quantitiesSignature(lines: QuantityLine[]): string {
  const lineKeys = lines.map((line) => `${line.fridge_id}:${line.product_id}:${line.qty}`)
  return lineKeys.sort().join('|')
}

/** Download the dispatch Excel file through the browser. */
export async function downloadDispatchExcel(dispatch: DispatchRead): Promise<void> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(`${API_BASE_URL}/api/v1/dispatches/${dispatch.id}/export.xlsx`, {
    headers,
  })
  if (!response.ok) {
    throw new Error(`Excel download failed (HTTP ${response.status})`)
  }
  const excelFile = await response.blob()
  const objectUrl = URL.createObjectURL(excelFile)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = `dispatch_${dispatch.delivery_date}.xlsx`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(objectUrl)
}
