import * as React from 'react'
import { useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { api, ApiError, type Page } from '@/lib/api'
import { toast } from '@/components/ui/sonner'
import { isRunFinished, type SyncFeed, type SyncRun, type SyncTriggerResponse } from './types'

const POLL_INTERVAL_MS = 3000

/** Latest checkpoint for an endpoint — powers the "last synced" stamp. */
export function useLatestSyncRun(endpoint: string) {
  return useQuery({
    queryKey: ['sync', 'runs', 'latest', endpoint],
    queryFn: ({ signal }) =>
      api.get<Page<SyncRun>>('/api/v1/sync/runs', { params: { endpoint, limit: 1 }, signal }),
    select: (page) => page.items[0] ?? null,
    staleTime: 30_000,
  })
}

export interface UseHuskySyncOptions {
  feed: SyncFeed
  /** sync_run.endpoint to poll (feed→endpoint mapping, e.g. catalogue). */
  endpoint: string
  /** Query keys to invalidate once the run finishes (e.g. products list). */
  invalidateKeys: QueryKey[]
  /** Noun for the completion toast, e.g. "product". */
  itemLabel: string
}

export interface UseHuskySyncResult {
  trigger: () => void
  isSyncing: boolean
}

/**
 * Trigger a Husky sync and poll the checkpoint list until the started run
 * finishes, then invalidate the affected queries and toast the record counts.
 */
export function useHuskySync({
  feed,
  endpoint,
  invalidateKeys,
  itemLabel,
}: UseHuskySyncOptions): UseHuskySyncResult {
  const queryClient = useQueryClient()
  const [runId, setRunId] = React.useState<number | null>(null)

  const triggerMutation = useMutation({
    mutationFn: () => api.post<SyncTriggerResponse>(`/api/v1/sync/husky/${feed}`),
    onSuccess: (response) => {
      toast.info(`Husky ${feed} sync started — this can take a few minutes…`)
      setRunId(response.sync_run_id)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Failed to start sync'),
  })

  const pollQuery = useQuery({
    queryKey: ['sync', 'runs', 'poll', endpoint, runId],
    queryFn: ({ signal }) =>
      api.get<Page<SyncRun>>('/api/v1/sync/runs', { params: { endpoint, limit: 20 }, signal }),
    enabled: runId !== null,
    refetchInterval: (query) => {
      const run = query.state.data?.items.find((item) => item.id === runId)
      return isRunFinished(run) ? false : POLL_INTERVAL_MS
    },
  })

  React.useEffect(() => {
    if (runId === null || !pollQuery.data) return
    const run = pollQuery.data.items.find((item) => item.id === runId)
    if (!isRunFinished(run) || !run) return

    // Refresh the "last synced" stamp and the affected domain lists.
    queryClient.invalidateQueries({ queryKey: ['sync', 'runs'] })
    for (const key of invalidateKeys) {
      queryClient.invalidateQueries({ queryKey: key })
    }

    if (run.status === 'failed') {
      toast.error(`Husky ${feed} sync failed${run.error ? `: ${run.error}` : ''}`)
    } else {
      toast.success(
        `Husky ${feed} sync complete — ${run.records_upserted} ${itemLabel} record${run.records_upserted === 1 ? '' : 's'} updated`,
      )
    }
    setRunId(null)
  }, [pollQuery.data, runId, feed, itemLabel, invalidateKeys, queryClient])

  return {
    trigger: () => triggerMutation.mutate(),
    isSyncing: triggerMutation.isPending || runId !== null,
  }
}
