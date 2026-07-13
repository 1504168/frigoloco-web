import * as React from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { PageHeader } from '@/components/shared/PageHeader'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { StatusChip } from '@/components/shared/StatusChip'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api, type Page } from '@/lib/api'
import { EMPTY_PLACEHOLDER, formatDateTime } from '@/lib/format'
import { SYNC_OVERRIDE_CAPTION } from '@/pages/masters/sync/components'
import type { SyncRun } from '@/pages/masters/sync/types'

const PAGE_LIMIT = 50
const ALL_ENDPOINTS = '__all__'

/** Known sync_run.endpoint values (verified live). */
const ENDPOINT_OPTIONS: { value: string; label: string }[] = [
  { value: ALL_ENDPOINTS, label: 'All endpoints' },
  { value: 'catalogue', label: 'Catalogue' },
  { value: 'fridgeproductprice', label: 'Fridge prices' },
  { value: 'purchases', label: 'Purchases' },
  { value: 'restock', label: 'Restock' },
  { value: 'productreview', label: 'Reviews' },
  { value: 'stock_current', label: 'Stock' },
]

/** A run is still in flight when it has no finish timestamp. */
function isRunning(run: SyncRun): boolean {
  return !run.finished_at || run.status === 'running'
}

function statusChip(run: SyncRun) {
  if (run.status === 'success') return <StatusChip status="done" label="Success" />
  if (run.status === 'failed') return <StatusChip status="critical" label="Failed" />
  if (run.status === 'empty') return <StatusChip status="neutral" label="Empty" />
  if (isRunning(run)) return <StatusChip status="pending" label="Running" />
  return <StatusChip status={run.status} />
}

export function SyncPage() {
  const [endpoint, setEndpoint] = React.useState<string>(ALL_ENDPOINTS)

  const runsQuery = useQuery({
    queryKey: ['sync', 'runs', 'history', endpoint],
    queryFn: ({ signal }) =>
      api.get<Page<SyncRun>>('/api/v1/sync/runs', {
        params: {
          endpoint: endpoint === ALL_ENDPOINTS ? undefined : endpoint,
          limit: PAGE_LIMIT,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
    // Auto-refresh while any run is still in flight.
    refetchInterval: (query) =>
      query.state.data?.items.some(isRunning) ? 3000 : false,
  })

  const runs = runsQuery.data?.items ?? []
  const anyRunning = runs.some(isRunning)

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="Masters / Sync"
        title="Husky Sync"
        description={SYNC_OVERRIDE_CAPTION}
        actions={
          <Select value={endpoint} onValueChange={setEndpoint}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ENDPOINT_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {anyRunning ? (
        <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
          A sync is running - this list refreshes automatically.
        </div>
      ) : null}

      {runsQuery.isError ? (
        <ErrorState error={runsQuery.error} onRetry={() => runsQuery.refetch()} />
      ) : runsQuery.isLoading ? (
        <LoadingSkeleton rows={10} columns={7} />
      ) : runs.length === 0 ? (
        <EmptyState title="No sync runs" description="Trigger a sync from the Products or Fridges page." />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Endpoint</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Fetched</TableHead>
                <TableHead className="text-right">Upserted</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Finished</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.id}>
                  <TableCell className="font-medium">{run.job}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{run.endpoint}</TableCell>
                  <TableCell>
                    {statusChip(run)}
                    {run.error ? (
                      <span className="mt-0.5 block max-w-xs truncate text-[11px] text-critical" title={run.error}>
                        {run.error}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{run.records_fetched}</TableCell>
                  <TableCell className="text-right tabular-nums">{run.records_upserted}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{formatDateTime(run.started_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {run.finished_at ? formatDateTime(run.finished_at) : EMPTY_PLACEHOLDER}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

export default SyncPage
