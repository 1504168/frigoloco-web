import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BellOff, Check } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusChip } from '@/components/shared/StatusChip'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { api, ApiError, type Page } from '@/lib/api'
import type { Alert } from '@/lib/types'
import { formatDateTime } from '@/lib/format'
import { ALERTS_COUNT_KEY } from '@/hooks/useAlertsCount'

const PAGE_SIZE = 25

type AckFilter = 'unacknowledged' | 'acknowledged' | 'all'

const ACK_PARAM: Record<AckFilter, boolean | undefined> = {
  unacknowledged: false,
  acknowledged: true,
  all: undefined,
}

/** Best-effort human summary of an alert's arbitrary JSON payload. */
function summarizePayload(payload: Record<string, unknown>): string {
  const candidate =
    (payload.message as string | undefined) ??
    (payload.summary as string | undefined) ??
    (payload.detail as string | undefined)
  if (candidate) return candidate
  const keys = Object.keys(payload)
  if (keys.length === 0) return '—'
  return keys.map((key) => `${key}: ${String(payload[key])}`).join(', ')
}

export function AlertsPage() {
  const queryClient = useQueryClient()
  const [ackFilter, setAckFilter] = React.useState<AckFilter>('unacknowledged')
  const [offset, setOffset] = React.useState(0)

  React.useEffect(() => {
    setOffset(0)
  }, [ackFilter])

  const alertsQuery = useQuery({
    queryKey: ['alerts', 'list', { ackFilter, limit: PAGE_SIZE, offset }],
    queryFn: ({ signal }) =>
      api.get<Page<Alert>>('/api/v1/alerts', {
        params: {
          acknowledged: ACK_PARAM[ackFilter],
          limit: PAGE_SIZE,
          offset,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const ackMutation = useMutation({
    mutationFn: (alertId: number) => api.put<Alert>(`/api/v1/alerts/${alertId}/ack`),
    onSuccess: (updated) => {
      toast.success(`Alert #${updated.id} acknowledged`)
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ALERTS_COUNT_KEY })
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Failed to acknowledge alert'
      toast.error(message)
    },
  })

  const columns = React.useMemo<DataTableColumn<Alert>[]>(
    () => [
      {
        id: 'type',
        header: 'Type',
        cell: (row) => <span className="font-medium">{row.alert_type}</span>,
        sortValue: (row) => row.alert_type,
      },
      {
        id: 'details',
        header: 'Details',
        cell: (row) => (
          <span className="text-muted-foreground">{summarizePayload(row.payload)}</span>
        ),
      },
      {
        id: 'status',
        header: 'Status',
        cell: (row) => <StatusChip status={row.status} />,
        sortValue: (row) => row.status,
      },
      {
        id: 'created',
        header: 'Created',
        cell: (row) => (
          <span className="whitespace-nowrap text-muted-foreground">
            {formatDateTime(row.created_at)}
          </span>
        ),
        sortValue: (row) => row.created_at,
      },
      {
        id: 'action',
        header: '',
        align: 'right',
        cell: (row) => {
          const isAcknowledged = row.acknowledged_at !== null
          if (isAcknowledged) {
            return (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Check className="h-3.5 w-3.5" /> Acknowledged
              </span>
            )
          }
          return (
            <Button
              size="sm"
              variant="outline"
              disabled={ackMutation.isPending && ackMutation.variables === row.id}
              onClick={() => ackMutation.mutate(row.id)}
            >
              Acknowledge
            </Button>
          )
        },
      },
    ],
    [ackMutation],
  )

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="System / Alerts"
        title="Alerts"
        description="Operational alerts raised by the forecasting and dispatch engines."
        actions={
          <Select value={ackFilter} onValueChange={(value) => setAckFilter(value as AckFilter)}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="unacknowledged">Unacknowledged</SelectItem>
              <SelectItem value="acknowledged">Acknowledged</SelectItem>
              <SelectItem value="all">All alerts</SelectItem>
            </SelectContent>
          </Select>
        }
      />

      <DataTable
        columns={columns}
        page={alertsQuery.data}
        isLoading={alertsQuery.isLoading}
        isError={alertsQuery.isError}
        error={alertsQuery.error}
        onRetry={() => alertsQuery.refetch()}
        limit={PAGE_SIZE}
        offset={offset}
        onOffsetChange={setOffset}
        getRowId={(row) => row.id}
        emptyState={
          <EmptyState
            icon={<BellOff className="h-8 w-8" />}
            title="No alerts"
            description={
              ackFilter === 'unacknowledged'
                ? 'Nothing needs your attention right now.'
                : 'No alerts match this filter.'
            }
          />
        }
      />
    </div>
  )
}

export default AlertsPage
