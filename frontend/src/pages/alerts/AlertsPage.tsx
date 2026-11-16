import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BellOff, Check } from 'lucide-react'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusChip } from '@/components/shared/StatusChip'
import { Toolbar } from '@/components/shared/Toolbar'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/toast'
import { api, ApiError, type Page } from '@/lib/api'
import type { Alert } from '@/lib/types'
import { EMPTY_PLACEHOLDER, formatDateTime12Hour } from '@/lib/format'
import { ALERTS_COUNT_KEY } from '@/hooks/useAlertsCount'
import { StockBlockedSummary } from '@/pages/alerts/StockBlockedSummary'

const PAGE_SIZE = 25

/** Summaries longer than this are clamped to a few lines with a "Show all" toggle. */
const LONG_DETAILS_CHARS = 240

const ALERT_TYPE_LABELS: Record<string, string> = {
  negative_blocked: 'Stock blocked',
  low_stock: 'Low stock',
  below_target: 'Below target',
  expiry: 'Expiry',
  rfid_offline: 'RFID offline',
}

type AckFilter = 'unacknowledged' | 'acknowledged' | 'all'

const ACK_PARAM: Record<AckFilter, boolean | undefined> = {
  unacknowledged: false,
  acknowledged: true,
  all: undefined,
}

const ACK_FILTER_LABELS: Record<AckFilter, string> = {
  unacknowledged: 'To handle',
  acknowledged: 'Handled',
  all: 'All',
}

const ACK_FILTER_OPTIONS = Object.keys(ACK_FILTER_LABELS) as AckFilter[]

const ACK_FILTER_HINT =
  'Mark an alert handled once you have dealt with it; it then moves from "To handle" to "Handled".'

/** "low_stock" -> "Low stock"; a type the backend adds later still reads as words. */
function alertTypeLabel(alertType: string): string {
  const knownLabel = ALERT_TYPE_LABELS[alertType]
  if (knownLabel) return knownLabel
  const words = alertType.replaceAll('_', ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** Best-effort human summary of an alert's arbitrary JSON payload. */
function summarizePayload(payload: Record<string, unknown>): string {
  const candidate =
    (payload.message as string | undefined) ??
    (payload.summary as string | undefined) ??
    (payload.detail as string | undefined)
  if (candidate) return candidate
  const keys = Object.keys(payload)
  if (keys.length === 0) return EMPTY_PLACEHOLDER
  return keys.map((key) => `${key}: ${formatPayloadValue(payload[key])}`).join(', ')
}

/** Nested lists and objects (e.g. offending_lines) print as JSON, not "[object Object]". */
function formatPayloadValue(value: unknown): string {
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value)
}

function AlertDetails({ payload }: { payload: Record<string, unknown> }) {
  const [expanded, setExpanded] = React.useState(false)
  const summary = summarizePayload(payload)
  const isLong = summary.length > LONG_DETAILS_CHARS
  const clampClass = isLong && !expanded ? 'line-clamp-3' : ''

  return (
    <div className="max-w-xl">
      <p className={`text-muted-foreground [overflow-wrap:anywhere] ${clampClass}`}>{summary}</p>
      {isLong && (
        <button
          type="button"
          className="mt-1 text-xs font-medium text-primary hover:underline"
          onClick={() => setExpanded((wasExpanded) => !wasExpanded)}
        >
          {expanded ? 'Show less' : 'Show all'}
        </button>
      )}
    </div>
  )
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
      toast.success(`Alert #${updated.id} marked handled`)
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ALERTS_COUNT_KEY })
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Failed to mark alert handled'
      toast.error(message)
    },
  })

  const columns = React.useMemo<DataTableColumn<Alert>[]>(
    () => [
      {
        id: 'type',
        header: 'Type',
        cell: (row) => (
          <span className="whitespace-nowrap font-medium">{alertTypeLabel(row.alert_type)}</span>
        ),
        sortValue: (row) => alertTypeLabel(row.alert_type),
      },
      {
        id: 'details',
        header: 'Details',
        // Sortable headers render inside a button, which drops the table's uppercase style.
        headerClassName: 'normal-case',
        cell: (row) =>
          row.stock_blocked ? (
            <StockBlockedSummary details={row.stock_blocked} />
          ) : (
            <AlertDetails payload={row.payload} />
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
            {formatDateTime12Hour(row.created_at)}
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
                <Check className="h-3.5 w-3.5" /> Handled
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
              Mark handled
            </Button>
          )
        },
      },
    ],
    [ackMutation],
  )

  return (
    <div className="space-y-3">
      <Toolbar
        left={
          <div className="flex items-center gap-3">
            <Select
              value={ackFilter}
              onValueChange={(value) => setAckFilter(value as AckFilter)}
            >
              <SelectTrigger
                className="w-36"
                aria-label="Show alerts"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ACK_FILTER_OPTIONS.map((option) => (
                  <SelectItem key={option} value={option}>
                    {ACK_FILTER_LABELS[option]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{ACK_FILTER_HINT}</p>
          </div>
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
