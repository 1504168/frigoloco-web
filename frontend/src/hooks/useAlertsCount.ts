import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '@/lib/api'
import type { Alert } from '@/lib/types'

/** Query key for the unacknowledged-alerts count badge (shared with the Alerts page). */
export const ALERTS_COUNT_KEY = ['alerts', 'count', 'unacknowledged'] as const

/**
 * Fetches the number of unacknowledged alerts to drive the sidebar badge.
 * Uses limit=1 and reads `total` so it stays cheap.
 */
export function useUnacknowledgedAlertsCount() {
  return useQuery({
    queryKey: ALERTS_COUNT_KEY,
    queryFn: () =>
      api.get<Page<Alert>>('/api/v1/alerts', {
        params: { acknowledged: false, limit: 1, offset: 0 },
      }),
    select: (page) => page.total,
    staleTime: 60_000,
  })
}
