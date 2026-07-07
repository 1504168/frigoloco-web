import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, PlayCircle } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Button } from '@/components/ui/button'
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
import { toast } from '@/components/ui/sonner'
import { api, ApiError, type Page } from '@/lib/api'
import { formatEuro, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type {
  CategoryReconTotal,
  Dispatch,
  Fridge,
  VerificationDetail,
  VerificationLine,
  VerificationSummary,
} from '@/pages/finance/types'
import { SectionCard } from '@/pages/finance/components'
import { toNumber } from '@/pages/finance/utils'

const PAGE_SIZE = 25

interface Category {
  id: number
  name: string
}

function diffClass(value: number): string {
  if (value > 0) return 'text-good-text'
  if (value < 0) return 'text-critical'
  return ''
}

export function VerificationsPage() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = React.useState(0)
  const [selectedId, setSelectedId] = React.useState<number | null>(null)
  const [dispatchId, setDispatchId] = React.useState<string>('')

  const listQuery = useQuery({
    queryKey: ['verifications', 'list', { offset }],
    queryFn: ({ signal }) =>
      api.get<Page<VerificationSummary>>('/api/v1/verifications', {
        params: { limit: PAGE_SIZE, offset },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const dispatchesQuery = useQuery({
    queryKey: ['dispatches', 'for-verify'],
    queryFn: ({ signal }) =>
      api.get<Page<Dispatch>>('/api/v1/dispatches', { params: { limit: 200 }, signal }),
    staleTime: 60_000,
  })

  const categoriesQuery = useQuery({
    queryKey: ['categories'],
    queryFn: ({ signal }) => api.get<Category[]>('/api/v1/categories', { signal }),
    staleTime: 5 * 60_000,
    select: (items) => new Map(items.map((category) => [category.id, category.name])),
  })

  const fridgesQuery = useQuery({
    queryKey: ['fridges', 'all'],
    queryFn: ({ signal }) =>
      api.get<Page<Fridge>>('/api/v1/fridges', { params: { limit: 500 }, signal }),
    staleTime: 5 * 60_000,
    select: (page) =>
      new Map(page.items.map((fridge) => [fridge.id, fridge.friendly_name || fridge.husky_name])),
  })

  const detailQuery = useQuery({
    queryKey: ['verifications', 'detail', selectedId],
    queryFn: ({ signal }) =>
      api.get<VerificationDetail>(`/api/v1/verifications/${selectedId}`, { signal }),
    enabled: selectedId !== null,
  })

  const verifyMutation = useMutation({
    mutationFn: (id: number) =>
      api.post<VerificationDetail>(`/api/v1/dispatches/${id}/verify`),
    onSuccess: (created) => {
      toast.success(`Verification #${created.id} created for dispatch #${created.dispatch_id}`)
      queryClient.invalidateQueries({ queryKey: ['verifications'] })
      queryClient.setQueryData(['verifications', 'detail', created.id], created)
      setSelectedId(created.id)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to verify dispatch')
    },
  })

  const categoryName = React.useCallback(
    (id: number) => categoriesQuery.data?.get(id) ?? `Category #${id}`,
    [categoriesQuery.data],
  )
  const fridgeName = React.useCallback(
    (id: number) => fridgesQuery.data?.get(id) ?? `Fridge #${id}`,
    [fridgesQuery.data],
  )

  const columns = React.useMemo<DataTableColumn<VerificationSummary>[]>(
    () => [
      {
        id: 'id',
        header: 'Verification',
        cell: (row) => <span className="font-medium">#{row.id}</span>,
        sortValue: (row) => row.id,
      },
      {
        id: 'dispatch',
        header: 'Dispatch',
        cell: (row) => <span className="tabular-nums">#{row.dispatch_id}</span>,
        sortValue: (row) => row.dispatch_id,
      },
      {
        id: 'run_at',
        header: 'Run at',
        cell: (row) => (
          <span className="whitespace-nowrap text-muted-foreground">{formatDateTime(row.run_at)}</span>
        ),
        sortValue: (row) => row.run_at,
      },
      {
        id: 'action',
        header: '',
        align: 'right',
        cell: (row) => (
          <Button size="sm" variant="outline" onClick={() => setSelectedId(row.id)}>
            View
          </Button>
        ),
      },
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="Operations / Verification"
        title="Verification"
        description="Dispatch reconciliation runs — compares dispatched vs added quantities per fridge, product and category."
        actions={
          <div className="flex flex-wrap items-end gap-2">
            <Select value={dispatchId} onValueChange={setDispatchId}>
              <SelectTrigger className="w-56">
                <SelectValue placeholder="Select a dispatch…" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {(dispatchesQuery.data?.items ?? []).map((dispatch) => (
                  <SelectItem key={dispatch.id} value={String(dispatch.id)}>
                    #{dispatch.id} · {dispatch.delivery_date} · {dispatch.status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              disabled={!dispatchId || verifyMutation.isPending}
              onClick={() => verifyMutation.mutate(Number(dispatchId))}
            >
              <PlayCircle className="mr-1.5 h-4 w-4" />
              {verifyMutation.isPending ? 'Verifying…' : 'Verify dispatch'}
            </Button>
          </div>
        }
      />

      <DataTable
        columns={columns}
        page={listQuery.data}
        isLoading={listQuery.isLoading}
        isError={listQuery.isError}
        error={listQuery.error}
        onRetry={() => listQuery.refetch()}
        limit={PAGE_SIZE}
        offset={offset}
        onOffsetChange={setOffset}
        getRowId={(row) => row.id}
        onRowClick={(row) => setSelectedId(row.id)}
        emptyState={
          <EmptyState
            icon={<ClipboardCheck className="h-8 w-8" />}
            title="No verifications yet"
            description="Run a verification for a dispatch above to reconcile dispatched vs added quantities."
          />
        }
      />

      {selectedId !== null ? (
        <VerificationDetailView
          detailQuery={detailQuery}
          categoryName={categoryName}
          fridgeName={fridgeName}
        />
      ) : null}
    </div>
  )
}

interface DetailViewProps {
  detailQuery: ReturnType<typeof useQuery<VerificationDetail>>
  categoryName: (id: number) => string
  fridgeName: (id: number) => string
}

function VerificationDetailView({ detailQuery, categoryName, fridgeName }: DetailViewProps) {
  if (detailQuery.isError) {
    return <ErrorState error={detailQuery.error} onRetry={() => detailQuery.refetch()} />
  }
  if (detailQuery.isLoading || !detailQuery.data) {
    return <LoadingSkeleton rows={6} columns={6} />
  }
  const detail = detailQuery.data

  return (
    <div className="space-y-6">
      <SectionCard
        title={`Category totals — verification #${detail.id}`}
        description={`Dispatch #${detail.dispatch_id} · run ${formatDateTime(detail.run_at)}`}
      >
        <ReconTable
          rows={detail.category_totals}
          firstHeader="Category"
          firstCell={(row) => categoryName(row.category_id)}
          rowKey={(row) => row.category_id}
        />
      </SectionCard>

      <SectionCard
        title="Per-line diff"
        description="UNRELIABLE = quantity the RFID/added import could not attribute reliably."
      >
        {detail.lines.length === 0 ? (
          <EmptyState title="No lines" description="This verification produced no reconciliation lines." />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fridge</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">Dispatched</TableHead>
                  <TableHead className="text-right">Added</TableHead>
                  <TableHead className="text-right">Unreliable</TableHead>
                  <TableHead className="text-right">Diff qty</TableHead>
                  <TableHead className="text-right">Diff value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.lines.map((line: VerificationLine) => (
                  <TableRow key={line.id}>
                    <TableCell className="font-medium">{fridgeName(line.fridge_id)}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      #{line.product_id}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{line.dispatched_qty}</TableCell>
                    <TableCell className="text-right tabular-nums">{line.added_qty}</TableCell>
                    <TableCell
                      className={cn(
                        'text-right tabular-nums',
                        line.unreliable_qty > 0 && 'font-semibold text-critical',
                      )}
                    >
                      {line.unreliable_qty}
                    </TableCell>
                    <TableCell className={cn('text-right tabular-nums', diffClass(line.diff_qty))}>
                      {line.diff_qty}
                    </TableCell>
                    <TableCell
                      className={cn('text-right tabular-nums', diffClass(toNumber(line.diff_value)))}
                    >
                      {formatEuro(line.diff_value)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </SectionCard>
    </div>
  )
}

interface ReconTableProps {
  rows: CategoryReconTotal[]
  firstHeader: string
  firstCell: (row: CategoryReconTotal) => string
  rowKey: (row: CategoryReconTotal) => number
}

function ReconTable({ rows, firstHeader, firstCell, rowKey }: ReconTableProps) {
  if (rows.length === 0) {
    return <EmptyState title="No category totals" description="Nothing to reconcile for this run." />
  }
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{firstHeader}</TableHead>
            <TableHead className="text-right">Dispatched</TableHead>
            <TableHead className="text-right">Added</TableHead>
            <TableHead className="text-right">Unreliable</TableHead>
            <TableHead className="text-right">Diff qty</TableHead>
            <TableHead className="text-right">Diff value</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={rowKey(row)}>
              <TableCell className="font-medium">{firstCell(row)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.dispatched_qty}</TableCell>
              <TableCell className="text-right tabular-nums">{row.added_qty}</TableCell>
              <TableCell
                className={cn(
                  'text-right tabular-nums',
                  row.unreliable_qty > 0 && 'font-semibold text-critical',
                )}
              >
                {row.unreliable_qty}
              </TableCell>
              <TableCell className={cn('text-right tabular-nums', diffClass(row.diff_qty))}>
                {row.diff_qty}
              </TableCell>
              <TableCell
                className={cn('text-right tabular-nums', diffClass(toNumber(row.diff_value)))}
              >
                {formatEuro(row.diff_value)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export default VerificationsPage
