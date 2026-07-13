import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { StatusChip } from '@/components/shared/StatusChip'
import { toast } from '@/components/ui/sonner'
import { api, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useHuskySync, useLatestSyncRun } from './hooks'
import type { EffectiveStatus, LocalStatus, StatusFilter, SyncFeed } from './types'

/** Human-facing caption explaining the override semantics (D5 contract). */
export const SYNC_OVERRIDE_CAPTION =
  'Active follows Husky sync; Inactive/Cancelled are manual overrides that survive every sync.'

// ─────────────────────── Sync button + last-sync stamp ───────────────────────

interface HuskySyncControlProps {
  feed: SyncFeed
  endpoint: string
  invalidateKeys: QueryKey[]
  itemLabel: string
}

/** "Sync from Husky" button with a live last-synced stamp beneath it. */
export function HuskySyncControl({ feed, endpoint, invalidateKeys, itemLabel }: HuskySyncControlProps) {
  const { trigger, isSyncing } = useHuskySync({ feed, endpoint, invalidateKeys, itemLabel })
  const latestRun = useLatestSyncRun(endpoint)
  const run = latestRun.data

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" onClick={trigger} disabled={isSyncing}>
        <RefreshCw className={cn('h-4 w-4', isSyncing && 'animate-spin')} />
        {isSyncing ? 'Syncing…' : 'Sync from Husky'}
      </Button>
      <span className="text-[11px] text-muted-foreground whitespace-nowrap">
        {latestRun.isLoading
          ? 'Loading…'
          : run
            ? `Last synced ${formatDateTime(run.finished_at ?? run.started_at)} · ${run.status}`
            : 'Never synced'}
      </span>
    </div>
  )
}

// ─────────────────────── Effective-status badge ───────────────────────

export function EffectiveStatusBadge({ status }: { status: EffectiveStatus }) {
  return <StatusChip status={status} />
}

// ─────────────────────── Per-row status override ───────────────────────

const FOLLOW_HUSKY = '__follow__'

function overrideValue(localStatus: LocalStatus): string {
  return localStatus ?? FOLLOW_HUSKY
}

interface StatusOverrideSelectProps {
  /** Entity resource path, e.g. `/api/v1/products/42`. */
  resourcePath: string
  localStatus: LocalStatus
  /** Queries to invalidate after a successful override. */
  invalidateKeys: QueryKey[]
  /** Label used in the success toast, e.g. product code. */
  entityLabel: string
}

/**
 * Row-level dropdown exposing the manual override. "Active (follow Husky)"
 * clears the override (local_status = null); Inactive/Cancelled force the value.
 */
export function StatusOverrideSelect({
  resourcePath,
  localStatus,
  invalidateKeys,
  entityLabel,
}: StatusOverrideSelectProps) {
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (next: LocalStatus) => api.put(resourcePath, { local_status: next }),
    onSuccess: (_data, next) => {
      const label =
        next === null ? 'now follows Husky' : `overridden to ${next}`
      toast.success(`${entityLabel} ${label}`)
      for (const key of invalidateKeys) {
        queryClient.invalidateQueries({ queryKey: key })
      }
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Failed to update status'),
  })

  return (
    <Select
      value={overrideValue(localStatus)}
      onValueChange={(value) => mutation.mutate(value === FOLLOW_HUSKY ? null : (value as LocalStatus))}
      disabled={mutation.isPending}
    >
      <SelectTrigger className="h-8 w-44 text-xs" aria-label="Status override">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={FOLLOW_HUSKY}>Active (follow Husky)</SelectItem>
        <SelectItem value="inactive">Inactive</SelectItem>
        <SelectItem value="cancelled">Cancelled</SelectItem>
      </SelectContent>
    </Select>
  )
}

// ─────────────────────── Server-side status filter ───────────────────────

interface StatusFilterSelectProps {
  value: StatusFilter
  onChange: (value: StatusFilter) => void
  className?: string
}

/** `?status=` filter select shared by the Products and Fridges lists. */
export function StatusFilterSelect({ value, onChange, className }: StatusFilterSelectProps) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as StatusFilter)}>
      <SelectTrigger className={cn('w-40', className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="active">Active only</SelectItem>
        <SelectItem value="inactive">Inactive only</SelectItem>
        <SelectItem value="cancelled">Cancelled only</SelectItem>
        <SelectItem value="all">All statuses</SelectItem>
      </SelectContent>
    </Select>
  )
}
