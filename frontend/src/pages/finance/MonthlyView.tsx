import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { EMPTY_PLACEHOLDER, formatEuro } from '@/lib/format'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { MonthlyAnalysis, MonthlyAnalysisRow, MonthlyDimension } from '@/pages/finance/types'
import { SectionCard, SegmentTabs } from '@/pages/finance/components'
import { MarginBarChart, type MarginBar } from '@/pages/finance/charts/MarginBarChart'
import { columnsForDimension, NAME_HEADER } from '@/pages/finance/monthlyColumns'
import {
  currentMonthKey,
  formatMonthLabel,
  recentMonths,
  shiftMonth,
} from '@/pages/finance/monthUtils'
import { sumField, toNumber } from '@/pages/finance/utils'

const MONTH_COUNT = 24
const CHART_MAX_ROWS = 12

type CompareMode = 'none' | 'prev' | 'yoy'

const DIMENSION_TABS: { value: MonthlyDimension; label: string }[] = [
  { value: 'client', label: 'By client (fridge)' },
  { value: 'supplier', label: 'By supplier' },
  { value: 'category', label: 'By category' },
]

function fetchMonthly(month: string, dimension: MonthlyDimension, signal?: AbortSignal) {
  return api.get<MonthlyAnalysis>('/api/v1/finance/monthly', {
    params: { month, dimension },
    signal,
  })
}

/** Signed euro cell colouring for margin columns. */
function signedClass(value: number): string {
  if (value > 0) return 'text-good-text'
  if (value < 0) return 'text-critical'
  return ''
}

export function MonthlyView() {
  const [dimension, setDimension] = React.useState<MonthlyDimension>('client')
  // Default to the previous month, which is where seeded data lives.
  const [month, setMonth] = React.useState(() => shiftMonth(currentMonthKey(), -1))
  const [compareMode, setCompareMode] = React.useState<CompareMode>('none')

  const monthOptions = React.useMemo(() => recentMonths(currentMonthKey(), MONTH_COUNT), [])

  const compareMonth =
    compareMode === 'prev' ? shiftMonth(month, -1) : compareMode === 'yoy' ? shiftMonth(month, -12) : null

  const monthlyQuery = useQuery({
    queryKey: ['finance', 'monthly', month, dimension],
    queryFn: ({ signal }) => fetchMonthly(month, dimension, signal),
  })

  const compareQuery = useQuery({
    queryKey: ['finance', 'monthly', compareMonth, dimension],
    queryFn: ({ signal }) => fetchMonthly(compareMonth as string, dimension, signal),
    enabled: compareMonth !== null,
  })

  const columns = React.useMemo(() => columnsForDimension(dimension), [dimension])
  const rows = monthlyQuery.data?.rows ?? []

  // Compare lookup: key_id (or key_name) -> net margin from the comparison month.
  const compareLookup = React.useMemo(() => {
    const map = new Map<string, number>()
    for (const row of compareQuery.data?.rows ?? []) {
      map.set(String(row.key_id ?? row.key_name), toNumber(row.net_margin))
    }
    return map
  }, [compareQuery.data])

  const compareNet = React.useCallback(
    (row: MonthlyAnalysisRow) => compareLookup.get(String(row.key_id ?? row.key_name)) ?? null,
    [compareLookup],
  )

  const chartData: MarginBar[] = React.useMemo(() => {
    const bars = rows.map((row) => ({ label: row.key_name, value: toNumber(row.net_margin) }))
    const sorted = [...bars].sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    return sorted.slice(0, CHART_MAX_ROWS).sort((a, b) => b.value - a.value)
  }, [rows])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <SegmentTabs
          tabs={DIMENSION_TABS}
          value={dimension}
          onChange={(value) => setDimension(value)}
        />
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Month
            <Select value={month} onValueChange={setMonth}>
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {monthOptions.map((option) => (
                  <SelectItem key={option} value={option}>
                    {formatMonthLabel(option)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Compare
            <Select value={compareMode} onValueChange={(value) => setCompareMode(value as CompareMode)}>
              <SelectTrigger className="w-52">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Compare: none</SelectItem>
                <SelectItem value="prev">Compare: previous month</SelectItem>
                <SelectItem value="yoy">Compare: same month last year</SelectItem>
              </SelectContent>
            </Select>
          </label>
        </div>
      </div>

      {dimension === 'client' ? (
        <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs text-foreground">
          <b>Cost basis, monthly by-fridge:</b> food cost uses the <b>DISPATCHED</b> value,
          intentionally different from the Weekly view (which uses <b>ADDED / restock</b> value).
        </div>
      ) : null}

      {monthlyQuery.isError ? (
        <ErrorState error={monthlyQuery.error} onRetry={() => monthlyQuery.refetch()} />
      ) : monthlyQuery.isLoading ? (
        <LoadingSkeleton rows={8} columns={columns.length + 1} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No P&L rows"
          description={`No ${dimension} data for ${formatMonthLabel(month)}.`}
        />
      ) : (
        <>
          <SectionCard
            title={`${NAME_HEADER[dimension]} P&L: ${formatMonthLabel(month)}`}
            description={
              compareMonth
                ? `${rows.length} rows · Δ column vs ${formatMonthLabel(compareMonth)}`
                : `${rows.length} rows`
            }
          >
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{NAME_HEADER[dimension]}</TableHead>
                    {columns.map((column) => (
                      <TableHead key={column.id} className="text-right">
                        {column.header}
                      </TableHead>
                    ))}
                    {compareMonth ? <TableHead className="text-right">Δ Net margin</TableHead> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => {
                    const compareValue = compareNet(row)
                    const delta =
                      compareValue === null ? null : toNumber(row.net_margin) - compareValue
                    return (
                      <TableRow key={String(row.key_id ?? row.key_name)}>
                        <TableCell className="font-medium">{row.key_name}</TableCell>
                        {columns.map((column) => {
                          const value = column.value(row)
                          return (
                            <TableCell
                              key={column.id}
                              className={cn(
                                'text-right tabular-nums',
                                column.signed && value !== null && signedClass(value),
                              )}
                            >
                              {column.render(row)}
                            </TableCell>
                          )
                        })}
                        {compareMonth ? (
                          <TableCell
                            className={cn(
                              'text-right tabular-nums',
                              delta !== null && signedClass(delta),
                            )}
                          >
                            {delta === null ? EMPTY_PLACEHOLDER : formatEuro(delta)}
                          </TableCell>
                        ) : null}
                      </TableRow>
                    )
                  })}
                </TableBody>
                <tfoot>
                  <TableRow className="border-t-2 border-baseline font-semibold">
                    <TableCell>Total</TableCell>
                    {columns.map((column) => {
                      const numericTotal = rows.reduce(
                        (sum, row) => sum + (column.value(row) ?? 0),
                        0,
                      )
                      const total = column.renderTotal
                        ? column.renderTotal(rows)
                        : formatEuro(numericTotal)
                      return (
                        <TableCell
                          key={column.id}
                          className={cn(
                            'text-right tabular-nums',
                            column.signed && signedClass(numericTotal),
                          )}
                        >
                          {total}
                        </TableCell>
                      )
                    })}
                    {compareMonth ? (
                      <TableCell className="text-right tabular-nums">
                        {formatEuro(
                          sumField(rows, (row) => row.net_margin) -
                            (compareQuery.data?.rows ?? []).reduce(
                              (sum, row) => sum + toNumber(row.net_margin),
                              0,
                            ),
                        )}
                      </TableCell>
                    ) : null}
                  </TableRow>
                </tfoot>
              </Table>
            </div>
          </SectionCard>

          <SectionCard
            title={`Net margin by ${NAME_HEADER[dimension].toLowerCase()}`}
            description={
              rows.length > CHART_MAX_ROWS
                ? `Top ${CHART_MAX_ROWS} of ${rows.length} by absolute net margin · blue = positive, red = negative · d3`
                : 'Blue = positive, red = negative · rendered with d3'
            }
          >
            <MarginBarChart data={chartData} />
          </SectionCard>
        </>
      )}
    </div>
  )
}
