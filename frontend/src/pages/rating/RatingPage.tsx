import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ChevronsUpDown, RefreshCw } from 'lucide-react'
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
import { api, ApiError } from '@/lib/api'
import { formatEuro } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ScoreRecomputeResult, ScorecardResponse, ScorecardRow } from '@/pages/rating/types'

const PAGE_SIZE = 25
const WINDOW_OPTIONS = [90, 180, 365] as const
type SortDirection = 'asc' | 'desc'

interface SortState {
  key: string
  direction: SortDirection
}

const DEFAULT_SORT: SortState = { key: 'final_score', direction: 'desc' }

/** Format a 0..1 fraction string as a percent (e.g. "1.0000" -> "100%"). */
function formatFraction(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  if (Number.isNaN(numeric)) return '—'
  return `${(numeric * 100).toFixed(numeric * 100 % 1 === 0 ? 0 : 1)}%`
}

/** Format a value already expressed in percent units (e.g. "10.0000" -> "10%"). */
function formatPercentUnits(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  if (Number.isNaN(numeric)) return '—'
  return `${numeric.toFixed(numeric % 1 === 0 ? 0 : 1)}%`
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat('nl-BE').format(value)
}

/** A single scorecard column. `sortKey` (when set) enables server-side sort. */
interface ScoreColumn {
  id: string
  header: string
  sortKey?: string
  align?: 'left' | 'right'
  cell: (row: ScorecardRow) => React.ReactNode
}

const COLUMNS: ScoreColumn[] = [
  { id: 'product_id', header: '#', align: 'right', cell: (r) => <span className="tabular-nums text-muted-foreground">{r.product_id}</span> },
  { id: 'code', header: 'Code', sortKey: 'code', cell: (r) => <span className="font-mono text-xs">{r.code}</span> },
  { id: 'name', header: 'Product', sortKey: 'name', cell: (r) => <span className="font-medium">{r.name}</span> },
  { id: 'category', header: 'Category', sortKey: 'category', cell: (r) => <span className="text-muted-foreground">{r.category}</span> },
  { id: 'brand', header: 'Brand', sortKey: 'brand', cell: (r) => <span className="text-muted-foreground">{r.brand ?? '—'}</span> },
  { id: 'shelf_life_days', header: 'Shelf life', sortKey: 'shelf_life_days', align: 'right', cell: (r) => <span className="tabular-nums">{r.shelf_life_days ?? '—'}</span> },
  { id: 'buying_price', header: 'Buy', sortKey: 'buying_price', align: 'right', cell: (r) => <span className="tabular-nums">{formatEuro(r.buying_price)}</span> },
  { id: 'sold_price', header: 'Sell', sortKey: 'sold_price', align: 'right', cell: (r) => <span className="tabular-nums">{formatEuro(r.sold_price)}</span> },
  { id: 'vat_rate', header: 'VAT', sortKey: 'vat_rate', align: 'right', cell: (r) => <span className="tabular-nums">{formatFraction(r.vat_rate)}</span> },
  { id: 'profit_margin', header: 'Margin', sortKey: 'profit_margin', align: 'right', cell: (r) => <span className="tabular-nums">{formatFraction(r.profit_margin)}</span> },
  { id: 'total_sold_qty', header: 'Sold qty', sortKey: 'total_sold_qty', align: 'right', cell: (r) => <span className="tabular-nums">{formatInteger(r.total_sold_qty)}</span> },
  { id: 'total_added_qty', header: 'Added qty', sortKey: 'total_added_qty', align: 'right', cell: (r) => <span className="tabular-nums">{formatInteger(r.total_added_qty)}</span> },
  { id: 'pct_sold', header: '% sold', sortKey: 'pct_sold', align: 'right', cell: (r) => <span className="tabular-nums">{formatPercentUnits(r.pct_sold)}</span> },
  { id: 'supplier_id', header: 'Supplier', align: 'right', cell: (r) => <span className="tabular-nums text-muted-foreground">{r.supplier_id ?? '—'}</span> },
  { id: 'positive_reviews', header: '+ reviews', sortKey: 'positive_reviews', align: 'right', cell: (r) => <span className="tabular-nums text-good-text">{r.positive_reviews}</span> },
  { id: 'negative_reviews', header: '− reviews', sortKey: 'negative_reviews', align: 'right', cell: (r) => <span className="tabular-nums text-critical">{r.negative_reviews}</span> },
  { id: 'pct_positive_review', header: '% positive', sortKey: 'pct_positive_review', align: 'right', cell: (r) => <span className="tabular-nums">{formatFraction(r.pct_positive_review)}</span> },
  { id: 'final_score', header: 'Score', sortKey: 'final_score', align: 'right', cell: (r) => <span className="font-semibold tabular-nums">{Number(r.final_score).toFixed(2)}</span> },
]

export function RatingPage() {
  const queryClient = useQueryClient()
  const [windowDays, setWindowDays] = React.useState<number>(365)
  const [offset, setOffset] = React.useState(0)
  const [sort, setSort] = React.useState<SortState>(DEFAULT_SORT)

  const sortParam = `${sort.key} ${sort.direction}`

  const scorecardQuery = useQuery({
    queryKey: ['rating', 'scorecard', { windowDays, offset, sortParam }],
    queryFn: ({ signal }) =>
      api.get<ScorecardResponse>('/api/v1/rating/scorecard', {
        params: { limit: PAGE_SIZE, offset, window_days: windowDays, sort: sortParam },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const recomputeMutation = useMutation({
    mutationFn: () => api.post<ScoreRecomputeResult>('/api/v1/forecasts/scores/recompute', {}),
    onSuccess: (result) => {
      toast.success(`Recomputed ${formatInteger(result.products_scored)} product scores (as of ${result.period_end})`)
      queryClient.invalidateQueries({ queryKey: ['rating', 'scorecard'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Failed to recompute scores'),
  })

  function toggleSort(column: ScoreColumn) {
    if (!column.sortKey) return
    setOffset(0)
    setSort((prev) => {
      if (prev.key !== column.sortKey) return { key: column.sortKey!, direction: 'desc' }
      if (prev.direction === 'desc') return { key: column.sortKey!, direction: 'asc' }
      return DEFAULT_SORT
    })
  }

  const data = scorecardQuery.data
  const rows = data?.items ?? []
  const total = data?.total ?? 0
  const weights = data?.weights
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rangeStart = total === 0 ? 0 : offset + 1
  const rangeEnd = Math.min(offset + PAGE_SIZE, total)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <div className="flex items-center gap-2">
          <Select
            value={String(windowDays)}
            onValueChange={(value) => {
              setWindowDays(Number(value))
              setOffset(0)
            }}
          >
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOW_OPTIONS.map((days) => (
                <SelectItem key={days} value={String(days)}>
                  Last {days} days
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={() => recomputeMutation.mutate()}
            disabled={recomputeMutation.isPending}
          >
            <RefreshCw className={cn('h-4 w-4', recomputeMutation.isPending && 'animate-spin')} />
            {recomputeMutation.isPending ? 'Recomputing…' : 'Recompute'}
          </Button>
        </div>
      </div>

      {scorecardQuery.isError ? (
        <ErrorState error={scorecardQuery.error} onRetry={() => scorecardQuery.refetch()} />
      ) : scorecardQuery.isLoading ? (
        <LoadingSkeleton rows={10} columns={8} />
      ) : rows.length === 0 ? (
        <EmptyState title="No scored products" description="Run Recompute to generate the scorecard." />
      ) : (
        <div className="space-y-3">
          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  {COLUMNS.map((column) => {
                    const isSorted = sort.key === column.sortKey && Boolean(column.sortKey)
                    return (
                      <TableHead
                        key={column.id}
                        className={cn('whitespace-nowrap', column.align === 'right' && 'text-right')}
                      >
                        {column.sortKey ? (
                          <button
                            type="button"
                            onClick={() => toggleSort(column)}
                            className={cn(
                              'inline-flex items-center gap-1 select-none transition-colors hover:text-foreground',
                              column.align === 'right' && 'flex-row-reverse',
                              isSorted && 'text-foreground',
                            )}
                          >
                            {column.header}
                            {isSorted ? (
                              sort.direction === 'asc' ? (
                                <ArrowUp className="h-3 w-3" />
                              ) : (
                                <ArrowDown className="h-3 w-3" />
                              )
                            ) : (
                              <ChevronsUpDown className="h-3 w-3 opacity-40" />
                            )}
                          </button>
                        ) : (
                          column.header
                        )}
                      </TableHead>
                    )
                  })}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.product_id}>
                    {COLUMNS.map((column) => (
                      <TableCell
                        key={column.id}
                        className={cn('whitespace-nowrap', column.align === 'right' && 'text-right')}
                      >
                        {column.cell(row)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              Showing <span className="font-medium text-foreground">{rangeStart}</span>–
              <span className="font-medium text-foreground">{rangeEnd}</span> of{' '}
              <span className="font-medium text-foreground">{formatInteger(total)}</span>
            </span>
            <div className="flex items-center gap-2">
              <span>
                Page {currentPage} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={offset <= 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default RatingPage
