import { InfoHint, type Hint } from '@/components/shared/InfoHint'
import { PageHeader } from '@/components/shared/PageHeader'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { KpiTile } from '@/pages/finance/components'
import { formatCount } from '@/pages/finance/utils'
import { ReportState } from '@/pages/reports/ReportState'
import { ReportToolbar, useReportScope } from '@/pages/reports/ReportToolbar'
import { useReport, useReportExport } from '@/pages/reports/reportsApi'
import type { RestockReport, RestockReportRow } from '@/pages/reports/types'

const DEFAULT_RANGE_DAYS = 7
const GAP_HINT: Hint = {
  text:
    'Units scanned in (ADDED) minus units dispatched. Negative means units left the warehouse ' +
    'but were never scanned into the fridge.',
  example: 'Dispatched 12, added 10: gap -2, two units to look for.',
}

function gapTone(gapQty: number): 'default' | 'critical' {
  if (gapQty < 0) return 'critical'
  return 'default'
}

function restockRowKey(row: RestockReportRow): string {
  return `${row.delivery_date}-${row.fridge_id}-${row.product_id}`
}

/** Dispatched quantity vs units scanned in (ADDED) per delivery day, fridge and product. */
export function RestockReportPage() {
  const [scope, setScope] = useReportScope(DEFAULT_RANGE_DAYS)
  const reportQuery = useReport<RestockReport>('restock', scope)
  const exportMutation = useReportExport('restock', scope)

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb="Reports"
        title="Restock report"
        description="Dispatched quantity (shipped dispatch days) against valid ADDED restock scans, by Brussels day. Gap = added - dispatched; negative means units dispatched but not scanned in."
      />
      <ReportToolbar
        scope={scope}
        onScopeChange={setScope}
        onExport={() => exportMutation.mutate()}
        isExporting={exportMutation.isPending}
        canExport={Boolean(reportQuery.data)}
      />
      <ReportState query={reportQuery} emptyDescription="No dispatches or restocks in this range.">
        {(report) => <RestockReportBody report={report} />}
      </ReportState>
    </div>
  )
}

function RestockReportBody({ report }: { report: RestockReport }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <KpiTile label="Dispatched" value={formatCount(report.total_dispatched_qty)} />
        <KpiTile label="Added" value={formatCount(report.total_added_qty)} caption="Valid ADDED scans" />
        <KpiTile
          label="Gap"
          value={formatCount(report.total_gap_qty)}
          tone={gapTone(report.total_gap_qty)}
          caption="Added - dispatched"
        />
      </div>
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Day</TableHead>
              <TableHead>Fridge</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Code</TableHead>
              <TableHead>Product</TableHead>
              <TableHead className="text-right">Dispatched</TableHead>
              <TableHead className="text-right">Added</TableHead>
              <TableHead className="text-right">
                <span className="inline-flex items-center gap-1">
                  Gap <InfoHint {...GAP_HINT} />
                </span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.rows.map((row) => (
              <TableRow key={restockRowKey(row)}>
                <TableCell>{formatDate(row.delivery_date)}</TableCell>
                <TableCell>{row.fridge_name}</TableCell>
                <TableCell className="text-muted-foreground">{row.category}</TableCell>
                <TableCell className="font-mono text-xs">{row.product_code}</TableCell>
                <TableCell className="font-medium">{row.product_name}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(row.dispatched_qty)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(row.added_qty)}</TableCell>
                <TableCell
                  className={cn('text-right tabular-nums', row.gap_qty < 0 && 'text-critical')}
                >
                  {formatCount(row.gap_qty)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
