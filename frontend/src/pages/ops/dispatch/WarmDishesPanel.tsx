import * as React from 'react'
import { ErrorState } from '@/components/shared/ErrorState'
import type { Hint } from '@/components/shared/InfoHint'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { buildWarmDishTable, type WarmDishRow } from '@/pages/ops/dispatch/warmDishTable'
import { useWarmDishLines, type IsoWeek } from '@/pages/ops/dispatch/weekOverviewApi'
import { ImportOptionSwitch } from '@/pages/ops/menu/ImportOptionSwitch'

interface WarmDishesPanelProps {
  isoWeek: IsoWeek
}

const INCLUDE_PLANNED_HINT: Hint = {
  text: 'Also counts the saved (planned) dispatches that are not dispatched yet.',
  example: 'A planned Thursday dispatch of 20 warm dishes adds 20 to the totals.',
}
const DAY_LABEL_FORMAT: Intl.DateTimeFormatOptions = {
  weekday: 'short',
  day: '2-digit',
  month: '2-digit',
}

/** Read-only distribution of the week's warm dishes: product x fridge x delivery day. */
export function WarmDishesPanel({ isoWeek }: WarmDishesPanelProps) {
  const [includePlanned, setIncludePlanned] = React.useState(false)
  const warmDishQuery = useWarmDishLines(isoWeek, includePlanned)

  function renderTable() {
    if (warmDishQuery.isError) {
      return (
        <ErrorState
          title="Failed to load the warm dish distribution"
          error={warmDishQuery.error}
          onRetry={() => warmDishQuery.refetch()}
        />
      )
    }
    if (!warmDishQuery.data) return <LoadingSkeleton rows={6} columns={6} />
    if (warmDishQuery.data.length === 0) {
      return <p className="text-xs text-muted-foreground">No warm dishes in this week yet.</p>
    }
    const warmDishTable = buildWarmDishTable(warmDishQuery.data)
    const { deliveryDates } = warmDishTable
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Product / fridge</TableHead>
            {deliveryDates.map((deliveryDate) => (
              <TableHead
                key={deliveryDate}
                className="text-right"
              >
                {formatDayLabel(deliveryDate)}
              </TableHead>
            ))}
            <TableHead className="text-right">Total</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {warmDishTable.productGroups.map((productGroup) => (
            <React.Fragment key={productGroup.product.key}>
              <QuantityRow
                row={productGroup.product}
                deliveryDates={deliveryDates}
                className="bg-muted/40 font-semibold"
                title={productGroup.categoryName}
              />
              {productGroup.fridges.map((fridgeRow) => (
                <QuantityRow
                  key={fridgeRow.key}
                  row={fridgeRow}
                  deliveryDates={deliveryDates}
                  className="text-muted-foreground"
                  indent
                />
              ))}
            </React.Fragment>
          ))}
          <QuantityRow
            row={warmDishTable.totals}
            deliveryDates={deliveryDates}
            className="border-t-2 font-semibold"
          />
        </TableBody>
      </Table>
    )
  }

  return (
    <section className="space-y-2 rounded-xl border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Warm dishes distribution</h2>
        <ImportOptionSwitch
          id="warm-include-planned"
          label="Include planned"
          hint={INCLUDE_PLANNED_HINT}
          checked={includePlanned}
          onCheckedChange={setIncludePlanned}
        />
      </div>
      {renderTable()}
    </section>
  )
}

interface QuantityRowProps {
  row: WarmDishRow
  deliveryDates: string[]
  className?: string
  title?: string
  indent?: boolean
}

function QuantityRow({ row, deliveryDates, className, title, indent = false }: QuantityRowProps) {
  return (
    <TableRow
      className={className}
      title={title}
    >
      <TableCell className={cn(indent && 'pl-8')}>{row.label}</TableCell>
      {deliveryDates.map((deliveryDate) => (
        <TableCell
          key={deliveryDate}
          className="text-right tabular-nums"
        >
          {row.qtyByDate.get(deliveryDate) ?? ''}
        </TableCell>
      ))}
      <TableCell className="text-right tabular-nums">{row.total}</TableCell>
    </TableRow>
  )
}

function formatDayLabel(deliveryDate: string): string {
  return new Date(`${deliveryDate}T00:00:00`).toLocaleDateString('en-GB', DAY_LABEL_FORMAT)
}
