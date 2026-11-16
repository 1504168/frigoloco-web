import { formatEuro } from '@/lib/format'

export interface DispatchTotals {
  fridgeCount: number
  fridgesToDispatch: number
  totalUnits: number
  totalCostEuros: number
}

export interface DispatchSummaryProps {
  totals: DispatchTotals
  /** True when the cost comes from the prices snapshot at dispatch time. */
  isSnapshotCost: boolean
}

/** Summary bar over the grid, mirroring the legacy Dispatch View totals. */
export function DispatchSummary({ totals, isSnapshotCost }: DispatchSummaryProps) {
  const costLabel = isSnapshotCost ? 'Cost at dispatch' : 'Total cost'
  return (
    <div className="flex flex-wrap divide-x divide-border overflow-hidden rounded-xl border border-border bg-card">
      <SummaryStat label="Scheduled fridges" value={String(totals.fridgeCount)} />
      <SummaryStat label="Fridges to dispatch" value={String(totals.fridgesToDispatch)} />
      <SummaryStat label="Total units" value={String(totals.totalUnits)} />
      <SummaryStat label={costLabel} value={formatEuro(totals.totalCostEuros)} />
    </div>
  )
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-[9rem] flex-1 flex-col px-4 py-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="text-base font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  )
}
