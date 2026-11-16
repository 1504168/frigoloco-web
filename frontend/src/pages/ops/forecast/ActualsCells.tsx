import { ArrowDown, ArrowUp } from 'lucide-react'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ForecastActualCell } from '@/pages/ops/lib/types'

const LOW_RATIO = 0.7
const GOOD_RATIO = 0.9
const AVERAGE_FMT = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 })

interface ActualsCellProps {
  cell: ForecastActualCell | undefined
  /** Divides added and sold for the per-week average view; 1 shows window totals. */
  divisor: number
}

/** "added → sold" with the sell-through ratio; a missing cell means 0 → 0. */
export function ActualsCell({ cell, divisor }: ActualsCellProps) {
  const added = (cell?.added_qty ?? 0) / divisor
  const sold = (cell?.sold_qty ?? 0) / divisor
  return (
    <div className="flex items-center justify-center gap-1.5 whitespace-nowrap">
      <span className="tabular-nums text-foreground">
        {AVERAGE_FMT.format(added)} → {AVERAGE_FMT.format(sold)}
      </span>
      <RatioBadge ratio={cell?.ratio ?? null} />
    </div>
  )
}

/** Sell-through ratio as a colour-coded percentage with an up/down trend icon. */
function RatioBadge({ ratio }: { ratio: string | null }) {
  if (ratio === null) {
    return <span className="text-muted-foreground">{EMPTY_PLACEHOLDER}</span>
  }
  const value = Number(ratio)
  const Icon = value < LOW_RATIO ? ArrowDown : ArrowUp
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 font-medium tabular-nums',
        ratioClass(value),
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      {Math.round(value * 100)}%
    </span>
  )
}

function ratioClass(ratio: number): string {
  if (ratio < LOW_RATIO) return 'text-critical'
  if (ratio >= GOOD_RATIO) return 'text-good-text'
  return 'text-warning'
}
