import * as React from 'react'
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ChevronsUpDown, RefreshCw } from 'lucide-react'
import { CategoryFilter } from '@/components/filters/CategoryFilter'
import { ProductSearchInput } from '@/components/filters/ProductSearchInput'
import { SupplierFilter } from '@/components/filters/SupplierFilter'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Toolbar } from '@/components/shared/Toolbar'
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
import { toast } from '@/components/ui/toast'
import { useCategorySupplierFilter } from '@/hooks/useCategorySupplierFilter'
import { api, ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { buildScoreColumns, formatInteger, type ScoreColumn } from '@/pages/rating/scorecardColumns'
import type {
  ScoreRecomputeRequest,
  ScoreRecomputeResult,
  ScorecardResponse,
} from '@/pages/rating/types'

const PAGE_SIZE = 25
const WINDOW_OPTIONS = [90, 180, 365] as const
const DEFAULT_WINDOW_DAYS = 365
type SortDirection = 'asc' | 'desc'

interface SortState {
  key: string
  direction: SortDirection
}

const DEFAULT_SORT: SortState = { key: 'final_score', direction: 'desc' }

const COMPUTED_AT_FORMATTER = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Dhaka',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
})

function buildWindowHint(windowDays: number): string {
  return (
    `Scores use sales, restocks and reviews from the last ${windowDays} days,` +
    ' ending on the day they were computed.'
  )
}

export function RatingPage() {
  const queryClient = useQueryClient()
  const [windowDays, setWindowDays] = React.useState<number>(DEFAULT_WINDOW_DAYS)
  const [offset, setOffset] = React.useState(0)
  const [sort, setSort] = React.useState<SortState>(DEFAULT_SORT)
  const [search, setSearch] = React.useState('')
  const { categoryId, supplierId, setCategoryId, setSupplierId } = useCategorySupplierFilter()

  const sortParam = `${sort.key} ${sort.direction}`
  const scorecardParams = {
    limit: PAGE_SIZE,
    offset,
    window_days: windowDays,
    sort: sortParam,
    category_id: categoryId ?? undefined,
    supplier_id: supplierId ?? undefined,
    search: search || undefined,
  }

  const scorecardQuery = useQuery({
    queryKey: ['rating', 'scorecard', scorecardParams],
    queryFn: ({ signal }) =>
      api.get<ScorecardResponse>('/api/v1/rating/scorecard', {
        params: scorecardParams,
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const recomputeMutation = useMutation({
    mutationFn: (request: ScoreRecomputeRequest) =>
      api.post<ScoreRecomputeResult>('/api/v1/forecasts/scores/recompute', request),
    onSuccess: (result) => {
      toast.success(
        `Recomputed ${formatInteger(result.products_scored)} product scores` +
          ` for the last ${result.window_days} days`,
      )
      queryClient.invalidateQueries({ queryKey: ['rating', 'scorecard'] })
      queryClient.invalidateQueries({ queryKey: ['ops', 'scores'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Failed to recompute scores'),
  })

  function selectWindow(value: string) {
    setWindowDays(Number(value))
    setOffset(0)
  }

  function selectCategory(nextCategoryId: number | null) {
    setCategoryId(nextCategoryId)
    setOffset(0)
  }

  function selectSupplier(nextSupplierId: number | null) {
    setSupplierId(nextSupplierId)
    setOffset(0)
  }

  function changeSearch(nextSearch: string) {
    setSearch(nextSearch)
    setOffset(0)
  }

  function toggleSort(column: ScoreColumn) {
    const sortKey = column.sortKey
    if (sortKey === undefined) return
    setOffset(0)
    setSort((previous) => {
      if (previous.key !== sortKey) return { key: sortKey, direction: 'desc' }
      if (previous.direction === 'desc') return { key: sortKey, direction: 'asc' }
      return DEFAULT_SORT
    })
  }

  const scorecard = scorecardQuery.data
  const columns = buildScoreColumns(scorecard?.weights)
  const windowHint = buildWindowHint(windowDays)

  return (
    <div className="space-y-3">
      <Toolbar
        left={
          <>
            <div title={windowHint}>
              <Select
                value={String(windowDays)}
                onValueChange={selectWindow}
              >
                <SelectTrigger
                  className="h-9 w-36"
                  aria-label={windowHint}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WINDOW_OPTIONS.map((days) => (
                    <SelectItem
                      key={days}
                      value={String(days)}
                    >
                      Last {days} days
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <CategoryFilter
              value={categoryId}
              onChange={selectCategory}
              className="h-9"
            />
            <SupplierFilter
              value={supplierId}
              onChange={selectSupplier}
              categoryId={categoryId}
              className="h-9"
            />
            <ProductSearchInput onSearchChange={changeSearch} />
          </>
        }
        right={
          <>
            <Button
              variant="outline"
              size="icon"
              className="shrink-0"
              onClick={() => recomputeMutation.mutate({ window_days: windowDays })}
              disabled={recomputeMutation.isPending}
              title={recomputeTooltip(windowDays, scorecard?.computed_at)}
              aria-label="Recompute scores"
            >
              <RefreshCw
                className={cn('h-4 w-4', recomputeMutation.isPending && 'animate-spin')}
              />
            </Button>
          </>
        }
      />

      <ScorecardBody
        scorecardQuery={scorecardQuery}
        columns={columns}
        windowDays={windowDays}
        sort={sort}
        offset={offset}
        onToggleSort={toggleSort}
        onOffsetChange={setOffset}
      />
    </div>
  )
}

function recomputeTooltip(windowDays: number, computedAt: string | null | undefined): string {
  const action = `Recompute scores for the last ${windowDays} days`
  if (!computedAt) return `${action} (never computed)`
  return `${action}\nLast computed ${COMPUTED_AT_FORMATTER.format(new Date(computedAt))}`
}

interface ScorecardBodyProps {
  scorecardQuery: UseQueryResult<ScorecardResponse>
  columns: ScoreColumn[]
  windowDays: number
  sort: SortState
  offset: number
  onToggleSort: (column: ScoreColumn) => void
  onOffsetChange: (offset: number) => void
}

function ScorecardBody({
  scorecardQuery,
  columns,
  windowDays,
  sort,
  offset,
  onToggleSort,
  onOffsetChange,
}: ScorecardBodyProps) {
  if (scorecardQuery.isError) {
    return (
      <ErrorState
        error={scorecardQuery.error}
        onRetry={() => scorecardQuery.refetch()}
      />
    )
  }
  const scorecard = scorecardQuery.data
  if (scorecard === undefined) {
    return (
      <LoadingSkeleton
        rows={10}
        columns={8}
      />
    )
  }
  if (scorecard.computed_at === null) {
    return (
      <EmptyState
        title={`Not computed yet for ${windowDays} days`}
        description="Press Recompute to calculate and store the scores for this window."
      />
    )
  }
  if (scorecard.items.length === 0) {
    return (
      <EmptyState
        title="No products match these filters"
        description="Change the category, supplier or search text."
      />
    )
  }

  const total = scorecard.total
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rangeEnd = Math.min(offset + PAGE_SIZE, total)

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto overflow-y-hidden rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((column) => (
                <TableHead
                  key={column.id}
                  title={column.hint}
                  className={cn('whitespace-nowrap', column.align === 'right' && 'text-right')}
                >
                  <SortableHeader
                    column={column}
                    sort={sort}
                    onToggleSort={onToggleSort}
                  />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {scorecard.items.map((row, index) => (
              <TableRow key={row.product_id}>
                {columns.map((column) => (
                  <TableCell
                    key={column.id}
                    className={cn('whitespace-nowrap', column.align === 'right' && 'text-right')}
                  >
                    {column.cell(row, offset + index + 1)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Showing <span className="font-medium text-foreground">{offset + 1}</span>-
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
            onClick={() => onOffsetChange(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => onOffsetChange(offset + PAGE_SIZE)}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  )
}

interface SortableHeaderProps {
  column: ScoreColumn
  sort: SortState
  onToggleSort: (column: ScoreColumn) => void
}

function SortableHeader({ column, sort, onToggleSort }: SortableHeaderProps) {
  if (column.sortKey === undefined) return <>{column.header}</>
  const isSorted = sort.key === column.sortKey
  return (
    <button
      type="button"
      onClick={() => onToggleSort(column)}
      className={cn(
        'inline-flex items-center gap-1 select-none transition-colors hover:text-foreground',
        column.align === 'right' && 'flex-row-reverse',
        isSorted && 'text-foreground',
      )}
    >
      {column.header}
      <SortIcon
        isSorted={isSorted}
        direction={sort.direction}
      />
    </button>
  )
}

function SortIcon({ isSorted, direction }: { isSorted: boolean; direction: SortDirection }) {
  if (!isSorted) return <ChevronsUpDown className="h-3 w-3 opacity-40" />
  if (direction === 'asc') return <ArrowUp className="h-3 w-3" />
  return <ArrowDown className="h-3 w-3" />
}

export default RatingPage
