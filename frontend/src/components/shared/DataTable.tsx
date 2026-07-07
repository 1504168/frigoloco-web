import * as React from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import type { Page } from '@/lib/api'
import { cn } from '@/lib/utils'

/** Column definition for {@link DataTable}. */
export interface DataTableColumn<T> {
  /** Stable id, also used as the React key. */
  id: string
  header: React.ReactNode
  /** Cell renderer for a row. */
  cell: (row: T) => React.ReactNode
  /**
   * Provide to make the column sortable. Returns the comparable value for a row.
   * Sorting is client-side over the current page's `items`.
   */
  sortValue?: (row: T) => string | number | null | undefined
  align?: 'left' | 'right' | 'center'
  headerClassName?: string
  cellClassName?: string
}

type SortDirection = 'asc' | 'desc'

interface SortState {
  columnId: string
  direction: SortDirection
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  /** Current page payload from the backend. */
  page?: Page<T>
  isLoading?: boolean
  isError?: boolean
  error?: unknown
  onRetry?: () => void
  /** Controlled pagination. `limit` and `offset` mirror the backend query. */
  limit: number
  offset: number
  onOffsetChange: (offset: number) => void
  getRowId: (row: T) => string | number
  onRowClick?: (row: T) => void
  emptyState?: React.ReactNode
  className?: string
}

const alignClass: Record<'left' | 'right' | 'center', string> = {
  left: 'text-left',
  right: 'text-right',
  center: 'text-center',
}

function compareValues(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): number {
  if (a === b) return 0
  if (a === null || a === undefined) return -1
  if (b === null || b === undefined) return 1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}

export function DataTable<T>({
  columns,
  page,
  isLoading,
  isError,
  error,
  onRetry,
  limit,
  offset,
  onOffsetChange,
  getRowId,
  onRowClick,
  emptyState,
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = React.useState<SortState | null>(null)

  const items = page?.items ?? []
  const total = page?.total ?? 0

  const sortedItems = React.useMemo(() => {
    if (!sort) return items
    const column = columns.find((c) => c.id === sort.columnId)
    if (!column?.sortValue) return items
    const accessor = column.sortValue
    const factor = sort.direction === 'asc' ? 1 : -1
    return [...items].sort((rowA, rowB) => factor * compareValues(accessor(rowA), accessor(rowB)))
  }, [items, sort, columns])

  function toggleSort(columnId: string) {
    setSort((prev) => {
      if (prev?.columnId !== columnId) return { columnId, direction: 'asc' }
      if (prev.direction === 'asc') return { columnId, direction: 'desc' }
      return null
    })
  }

  const currentPage = Math.floor(offset / limit) + 1
  const totalPages = Math.max(1, Math.ceil(total / limit))
  const rangeStart = total === 0 ? 0 : offset + 1
  const rangeEnd = Math.min(offset + limit, total)
  const canPrev = offset > 0
  const canNext = offset + limit < total

  if (isError) {
    return <ErrorState error={error} onRetry={onRetry} className={className} />
  }

  if (isLoading) {
    return <LoadingSkeleton rows={limit > 10 ? 10 : limit} columns={columns.length} className={className} />
  }

  if (items.length === 0) {
    return <>{emptyState ?? <EmptyState className={className} />}</>
  }

  return (
    <div className={cn('space-y-3', className)}>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((column) => {
                const isSorted = sort?.columnId === column.id
                const align = column.align ?? 'left'
                return (
                  <TableHead
                    key={column.id}
                    className={cn(alignClass[align], column.headerClassName)}
                  >
                    {column.sortValue ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(column.id)}
                        className={cn(
                          'inline-flex items-center gap-1 select-none hover:text-foreground transition-colors',
                          align === 'right' && 'flex-row-reverse',
                          isSorted && 'text-foreground',
                        )}
                      >
                        {column.header}
                        {isSorted ? (
                          sort?.direction === 'asc' ? (
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
            {sortedItems.map((row) => (
              <TableRow
                key={getRowId(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(onRowClick && 'cursor-pointer')}
              >
                {columns.map((column) => (
                  <TableCell
                    key={column.id}
                    className={cn(alignClass[column.align ?? 'left'], column.cellClassName)}
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
          <span className="font-medium text-foreground">{total}</span>
        </span>
        <div className="flex items-center gap-2">
          <span>
            Page {currentPage} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={!canPrev}
            onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!canNext}
            onClick={() => onOffsetChange(offset + limit)}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  )
}
