import type * as React from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'

const SKELETON_ROWS = 6
const SKELETON_COLUMNS = 6

interface ReportStateProps<T extends { rows: unknown[] }> {
  query: UseQueryResult<T>
  emptyDescription: string
  children: (report: T) => React.ReactNode
}

/** Shows the error, loading or empty state of a report query, else renders the report. */
export function ReportState<T extends { rows: unknown[] }>({
  query,
  emptyDescription,
  children,
}: ReportStateProps<T>) {
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  }
  const waitingForDates = !query.data && query.fetchStatus === 'idle'
  if (waitingForDates) {
    return <EmptyState title="Pick a date range" description="Fill in both From and To." />
  }
  if (!query.data) {
    return <LoadingSkeleton rows={SKELETON_ROWS} columns={SKELETON_COLUMNS} />
  }
  if (query.data.rows.length === 0) {
    return <EmptyState title="No data" description={emptyDescription} />
  }
  return <>{children(query.data)}</>
}
