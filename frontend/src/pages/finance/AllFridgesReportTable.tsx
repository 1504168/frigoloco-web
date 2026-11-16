import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { MoneyCell } from '@/components/shared/MoneyCell'
import type { AllFridgesReport, AllFridgesReportRow } from '@/pages/finance/types'
import { formatMarginPct, NOT_AVAILABLE } from '@/pages/finance/ReportKpiTiles'
import { formatCount } from '@/pages/finance/utils'

function FigureCells({ row }: { row: AllFridgesReportRow }) {
  return (
    <>
      <TableCell className="text-right tabular-nums">{formatCount(row.added_qty)}</TableCell>
      <TableCell className="text-right">
        <MoneyCell value={row.food_cost} />
      </TableCell>
      <TableCell className="text-right">
        <MoneyCell value={row.revenue} />
      </TableCell>
      <TableCell className="text-right">
        <MoneyCell value={row.revenue_ex_vat} />
      </TableCell>
      <TableCell className="text-right">
        <MoneyCell value={row.margin} />
      </TableCell>
      <TableCell className="text-right tabular-nums">{formatMarginPct(row.margin_pct)}</TableCell>
    </>
  )
}

/** One row per fridge with a totals footer (all-fridges report). */
export function AllFridgesReportTable({ report }: { report: AllFridgesReport }) {
  return (
    <div className="overflow-x-auto overflow-y-hidden rounded-xl border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Fridge</TableHead>
            <TableHead>Client</TableHead>
            <TableHead className="text-right">Added qty</TableHead>
            <TableHead className="text-right">Food cost</TableHead>
            <TableHead className="text-right">Revenue incl VAT</TableHead>
            <TableHead className="text-right">Revenue ex VAT</TableHead>
            <TableHead className="text-right">Food margin</TableHead>
            <TableHead className="text-right">Margin %</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {report.rows.map((row) => (
            <TableRow key={row.fridge_id}>
              <TableCell className="font-medium">{row.fridge_name}</TableCell>
              <TableCell className="text-muted-foreground">{row.client_name ?? NOT_AVAILABLE}</TableCell>
              <FigureCells row={row} />
            </TableRow>
          ))}
        </TableBody>
        <tfoot>
          <TableRow className="border-t-2 border-baseline font-semibold">
            <TableCell>{report.totals.fridge_name}</TableCell>
            <TableCell>{formatCount(report.rows.length)} fridges</TableCell>
            <FigureCells row={report.totals} />
          </TableRow>
        </tfoot>
      </Table>
    </div>
  )
}
