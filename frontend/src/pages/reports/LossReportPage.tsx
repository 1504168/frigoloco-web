import { InfoHint, type Hint } from '@/components/shared/InfoHint'
import { MoneyCell } from '@/components/shared/MoneyCell'
import { PageHeader } from '@/components/shared/PageHeader'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDate, formatEuro } from '@/lib/format'
import { KpiTile } from '@/pages/finance/components'
import { formatCount } from '@/pages/finance/utils'
import { ReportState } from '@/pages/reports/ReportState'
import { ReportToolbar, useReportScope } from '@/pages/reports/ReportToolbar'
import { useReport, useReportExport } from '@/pages/reports/reportsApi'
import type { LossReport, LossReportRow } from '@/pages/reports/types'

const DEFAULT_RANGE_DAYS = 28
const LOSS_CAVEAT_HINT: Hint = {
  text:
    'The fridge only reports that a unit was removed, not why, so moves between fridges count ' +
    'as loss too.',
  example: '5 drinks moved from fridge A to fridge B show as 5 removed (loss) at fridge A.',
}

function lossRowKey(row: LossReportRow): string {
  return `${row.week_start}-${row.fridge_id}-${row.product_id}`
}

/** Valid REMOVED restock scans valued at purchase price, per ISO week, fridge and product. */
export function LossReportPage() {
  const [scope, setScope] = useReportScope(DEFAULT_RANGE_DAYS)
  const reportQuery = useReport<LossReport>('loss', scope)
  const exportMutation = useReportExport('loss', scope)

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb="Reports"
        title="Loss report"
        description="Valid REMOVED restock scans valued at the product's current purchase price, by Brussels ISO week."
      />
      <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
        <span>
          Caveat: every REMOVED scan counts as a loss. A product moved from one fridge to another
          also shows up here as REMOVED, so the loss can be overstated.
        </span>
        <InfoHint {...LOSS_CAVEAT_HINT} />
      </div>
      <ReportToolbar
        scope={scope}
        onScopeChange={setScope}
        onExport={() => exportMutation.mutate()}
        isExporting={exportMutation.isPending}
        canExport={Boolean(reportQuery.data)}
      />
      <ReportState query={reportQuery} emptyDescription="No removed items in this range.">
        {(report) => <LossReportBody report={report} />}
      </ReportState>
    </div>
  )
}

function LossReportBody({ report }: { report: LossReport }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <KpiTile label="Removed items" value={formatCount(report.total_removed_qty)} />
        <KpiTile
          label="Loss cost"
          value={formatEuro(report.total_loss_cost)}
          tone="critical"
          caption="Removed qty x purchase price"
        />
      </div>
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Week</TableHead>
              <TableHead>Week start</TableHead>
              <TableHead>Fridge</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Code</TableHead>
              <TableHead>Product</TableHead>
              <TableHead className="text-right">Removed</TableHead>
              <TableHead className="text-right">Unit cost</TableHead>
              <TableHead className="text-right">Loss cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.rows.map((row) => (
              <TableRow key={lossRowKey(row)}>
                <TableCell>{`${row.iso_year}-W${row.iso_week}`}</TableCell>
                <TableCell>{formatDate(row.week_start)}</TableCell>
                <TableCell>{row.fridge_name}</TableCell>
                <TableCell className="text-muted-foreground">{row.category}</TableCell>
                <TableCell className="font-mono text-xs">{row.product_code}</TableCell>
                <TableCell className="font-medium">{row.product_name}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(row.removed_qty)}</TableCell>
                <TableCell className="text-right">
                  <MoneyCell value={row.unit_purchase_price} />
                </TableCell>
                <TableCell className="text-right">
                  <MoneyCell value={row.loss_cost} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
