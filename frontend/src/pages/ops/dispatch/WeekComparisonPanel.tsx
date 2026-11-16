import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  isoWeekLabel,
  useWeekComparison,
  type CategoryWeekUnits,
  type IsoWeek,
} from '@/pages/ops/dispatch/weekOverviewApi'

interface WeekComparisonPanelProps {
  isoWeek: IsoWeek
}

const TOTAL_CATEGORY_ID = -1

/** Planned or dispatched units per category next to the previous week and last year. */
export function WeekComparisonPanel({ isoWeek }: WeekComparisonPanelProps) {
  const comparisonQuery = useWeekComparison(isoWeek)
  if (comparisonQuery.isError) {
    return (
      <ErrorState
        title="Failed to load the week comparison"
        error={comparisonQuery.error}
        onRetry={() => comparisonQuery.refetch()}
      />
    )
  }
  if (!comparisonQuery.data) return <LoadingSkeleton rows={6} columns={6} />

  const comparison = comparisonQuery.data
  const totalRow = sumCategories(comparison.categories)
  const rows = [...comparison.categories, totalRow]
  return (
    <section className="space-y-2 rounded-xl border border-border bg-card p-3">
      <h2 className="text-sm font-semibold text-foreground">
        Units per category: planned or dispatched
      </h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Category</TableHead>
            <TableHead className="text-right">{isoWeekLabel(comparison.this_week)}</TableHead>
            <TableHead className="text-right">{isoWeekLabel(comparison.previous_week)}</TableHead>
            <TableHead className="text-right">vs previous</TableHead>
            <TableHead className="text-right">
              {isoWeekLabel(comparison.same_week_last_year)}
            </TableHead>
            <TableHead className="text-right">vs last year</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow
              key={row.category_id}
              className={row.category_id === TOTAL_CATEGORY_ID ? 'font-semibold' : undefined}
            >
              <TableCell>{row.category_name}</TableCell>
              <TableCell className="text-right tabular-nums">{row.this_week_units}</TableCell>
              <TableCell className="text-right tabular-nums">{row.previous_week_units}</TableCell>
              <ChangeCell current={row.this_week_units} compared={row.previous_week_units} />
              <TableCell className="text-right tabular-nums">{row.last_year_units}</TableCell>
              <ChangeCell current={row.this_week_units} compared={row.last_year_units} />
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {comparison.categories.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No planned or dispatched lines in these weeks yet.
        </p>
      ) : null}
    </section>
  )
}

function ChangeCell({ current, compared }: { current: number; compared: number }) {
  const change = current - compared
  const sign = change > 0 ? '+' : ''
  const changeText = compared === 0 ? '-' : `${sign}${change}`
  return <TableCell className="text-right tabular-nums text-muted-foreground">{changeText}</TableCell>
}

function sumCategories(categories: CategoryWeekUnits[]): CategoryWeekUnits {
  const totalRow: CategoryWeekUnits = {
    category_id: TOTAL_CATEGORY_ID,
    category_name: 'Total',
    this_week_units: 0,
    previous_week_units: 0,
    last_year_units: 0,
  }
  for (const category of categories) {
    totalRow.this_week_units += category.this_week_units
    totalRow.previous_week_units += category.previous_week_units
    totalRow.last_year_units += category.last_year_units
  }
  return totalRow
}
